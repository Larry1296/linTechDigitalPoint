import re
from django.views.decorators.csrf import csrf_protect
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers, permissions
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.throttling import AnonRateThrottle
from rest_framework.response import Response
from apps.accounts.api import LoginThrottle
from .context import organization_context
from .models import Organization, Membership, BranchMembership, OrganizationSubscription, MODULES
from .middleware import effective_modules
from .branches import authorized_stores
from . import business_profiles as profiles
from apps.cyber.models import CyberServiceProfile


def public_logo_path(organization, variant="logo"):
    from apps.commerce.receipts import logo_url
    return logo_url(organization, variant=variant)

def organization_data(organization):
    from apps.accounting.money_mode import money_mode, parts_data, structure
    from .billing import state
    subscription_view = state(organization)
    return {"id": organization.pk, "name": organization.name, "slug": organization.slug,
            "logo_url": public_logo_path(organization), "logo_dark_url": public_logo_path(organization, "logo_dark"),
            "currency": organization.currency, "country": organization.country, "timezone": organization.timezone,
            "business_model": organization.business_model, "sector": organization.sector, "business_type": organization.business_type,
            "enabled_modules": sorted(effective_modules(organization)), "money_mode": money_mode(organization),
            "structure": structure(organization), "parts": parts_data(organization),
            "subscription_status": subscription_view["status"],
            "subscription": subscription_view}

@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def platform_info(request):
    return Response({"name": settings.PLATFORM_NAME, "contact_email": settings.PLATFORM_CONTACT_EMAIL})

@api_view(["GET"])
def organizations(request):
    memberships = Membership.objects.filter(user=request.user, status="ACTIVE", organization__active=True).select_related("organization__subscription__plan")
    return Response([{"organization": organization_data(m.organization), "role": m.role} for m in memberships])

@api_view(["POST"])
def select_organization(request):
    value = serializers.IntegerField(min_value=1).run_validation(request.data.get("organization_id"))
    membership = Membership.objects.filter(user=request.user, organization_id=value, status="ACTIVE", organization__active=True).first()
    if not membership:
        return Response({"detail": "Business unavailable."}, status=403)
    request.session["organization_id"] = membership.organization_id
    request.session.pop("branch_id", None)
    return Response(organization_data(membership.organization))

def main_branch_id():
    from apps.core.models import Store
    return Store.objects.order_by("created_at", "pk").values_list("pk", flat=True).first()

def branch_data(store, request=None, main_id=None):
    selected = getattr(request, "store", None) if request else None
    main_id = main_id or main_branch_id()
    return {"id": store.pk, "name": store.name, "currency": store.currency, "timezone": store.timezone,
            "phone": store.phone, "email": store.email, "address": store.address,
            "is_active": selected is not None and selected.pk == store.pk, "is_main": store.pk == main_id}

@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def branches(request):
    from apps.core.models import Store
    if not request.organization or not request.membership:
        return Response({"detail": "Select an active business first.", "code": "organization_required"}, status=403)
    if request.method == "GET":
        stores = authorized_stores(request.user, request.membership)
        main_id = main_branch_id()
        return Response([branch_data(store, request, main_id) for store in stores])
    if request.membership.role not in {"OWNER", "ADMIN", "MANAGER"}:
        return Response({"detail": "Branch management permission required."}, status=403)
    form = BusinessInput(data={**request.data, "enabled_modules": request.organization.enabled_modules})
    form.is_valid(raise_exception=True)
    source = Store.objects.order_by("created_at", "pk").first()
    name = request.data.get("name") or f"{request.organization.name} Branch"
    user_id = request.data.get("admin_user_id")
    if user_id and not Membership.objects.filter(user_id=user_id, organization=request.organization, status="ACTIVE").exists():
        return Response({"detail": "The branch administrator must belong to this business."}, status=400)
    with transaction.atomic():
        store = Store.objects.create(name=name, currency=request.organization.currency,
                                     timezone=request.organization.timezone,
                                     measurement_unit=source.measurement_unit if source else "ft",
                                     phone=source.phone if source else "", email=source.email if source else "",
                                     address=request.data.get("address", source.address if source else ""))
        if user_id:
            BranchMembership.objects.create(user_id=user_id, store=store, role="ADMIN")
    return Response(branch_data(store, request), status=201)

class BranchInput(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    phone = serializers.CharField(max_length=30, allow_blank=True)
    email = serializers.EmailField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)


def branch_records(store):
    """Names of the business records that tie a branch to the books and stock history."""
    from django.db.models import Q
    from apps.accounting.models import CashEntry, JournalEntry
    from apps.commerce.models import Order, Sale
    from apps.cyber.models import CyberJob
    from apps.inventory.models import Movement, Reservation, StockAdjustment, StockBalance, StockReceipt
    from apps.mpesa.models import MpesaOutlet
    checks = [("sales", Sale.objects.filter(branch=store)), ("online orders", Order.objects.filter(branch=store)),
        ("stock receipts", StockReceipt.objects.filter(branch=store)), ("reservations", Reservation.objects.filter(branch=store)),
        ("service jobs", CyberJob.objects.filter(branch=store)), ("M-Pesa outlets", MpesaOutlet.objects.filter(store=store)),
        ("cash book entries", CashEntry.objects.filter(branch=store)), ("ledger entries", JournalEntry.objects.filter(branch=store)),
        ("stock", StockBalance.objects.filter(shelf__zone__store=store)),
        ("stock movements", Movement.objects.filter(Q(source__zone__store=store) | Q(destination__zone__store=store))),
        ("stock adjustments", StockAdjustment.objects.filter(shelf__zone__store=store))]
    return [label for label, rows in checks if rows.exists()]


@transaction.atomic
def remove_branch(store):
    """Deletes an unused branch with its empty shelf layout and staff assignments."""
    from apps.inventory.models import Shelf, ShelfHistory, ShelfLevel, ShelfStack, VariantPreferredLocation, Zone
    zones = Zone.objects.filter(store=store)
    shelves = Shelf.objects.filter(zone__in=zones)
    BranchMembership.objects.filter(store=store).delete()
    VariantPreferredLocation.objects.filter(shelf__in=shelves).delete()
    ShelfHistory.objects.filter(shelf__in=shelves).delete()
    shelves.filter(parent__isnull=False).delete()
    shelves.delete()
    ShelfLevel.objects.filter(stack__zone__in=zones).delete()
    ShelfStack.objects.filter(zone__in=zones).delete()
    zones.delete()
    store.delete()


@api_view(["PATCH", "DELETE"])
@permission_classes([permissions.IsAuthenticated])
def branch(request, pk):
    if not request.organization or not request.membership:
        return Response({"detail": "Select an active business first.", "code": "organization_required"}, status=403)
    store = authorized_stores(request.user, request.membership).filter(pk=pk).first()
    if not store:
        return Response({"detail": "Branch unavailable."}, status=404)
    if request.method == "PATCH":
        if request.membership.role not in {"OWNER", "ADMIN", "MANAGER"}:
            return Response({"detail": "Branch management permission required."}, status=403)
        form = BranchInput(store, data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        for field, value in form.validated_data.items():
            setattr(store, field, value)
        store.save(update_fields=[*form.validated_data, "updated_at"])
        return Response(branch_data(store, request))
    if request.membership.role not in {"OWNER", "ADMIN"}:
        return Response({"detail": "Only the owner or an administrator can delete a branch."}, status=403)
    if store.pk == main_branch_id():
        return Response({"detail": "The main branch cannot be deleted. You can still change its details."}, status=400)
    records = branch_records(store)
    if records:
        return Response({"detail": f"{store.name} cannot be deleted because it has {', '.join(records)}. "
                         "Deleting it would remove history your books depend on."}, status=400)
    remove_branch(store)
    if request.session.get("branch_id") == pk:
        request.session.pop("branch_id", None)
    return Response(status=204)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def select_branch(request):
    if not request.organization or not request.membership:
        return Response({"detail": "Select an active business first.", "code": "organization_required"}, status=403)
    try:
        branch_id = serializers.IntegerField(min_value=1).run_validation(request.data.get("branch_id"))
    except serializers.ValidationError:
        return Response({"detail": "Choose a valid branch."}, status=400)
    store = authorized_stores(request.user, request.membership).filter(pk=branch_id).first()
    if not store:
        return Response({"detail": "Branch unavailable."}, status=403)
    request.session["branch_id"] = store.pk
    request.store = store
    return Response(branch_data(store, request))

@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def business_profiles(request):
    """The kinds of business the platform serves and the tools each can use (static, public)."""
    return Response(profiles.catalogue())


class ProfileInput(serializers.Serializer):
    """How the business makes money, what kind it is, and the tools it uses. Checked together."""
    business_model = serializers.ChoiceField(choices=list(profiles.BUSINESS_MODELS), required=False)
    sector = serializers.CharField(max_length=40, allow_blank=True, required=False)
    business_size = serializers.ChoiceField(choices=list(profiles.SIZES), required=False)
    business_type = serializers.CharField(max_length=100, allow_blank=True, required=False)
    enabled_modules = serializers.ListField(child=serializers.ChoiceField(choices=MODULES))

    def validate(self, data):
        # Older clients send only tools; the way the business makes money then follows from them.
        model = data.setdefault("business_model", profiles.model_for_modules(data["enabled_modules"]))
        sector = data.get("sector", "")
        found = profiles.find_sector(sector, also=self.context.get("current_sector", "")) if sector else None
        if sector:
            if not found:
                raise serializers.ValidationError({"sector": "Choose your kind of business from the list."})
            if found[0] != model:
                raise serializers.ValidationError({"sector": "That kind of business does not match how your business makes money."})
            if sector in profiles.OTHER_SECTORS and not data.get("business_type", "").strip():
                raise serializers.ValidationError({"business_type": "Describe what your business does."})
        problems = profiles.module_problems(model, data["enabled_modules"])
        if problems:
            raise serializers.ValidationError({"enabled_modules": " ".join(problems)})
        data["enabled_modules"] = sorted(set(data["enabled_modules"]))
        # The label shown on the dashboard: the owner's own words for "other", otherwise the sector's name.
        if sector and sector not in profiles.OTHER_SECTORS:
            data["business_type"] = found[1]["label"]
        return data


class PartNames(serializers.DictField):
    """The owner's own names for the parts of the business, e.g. {"CYBER": "Salon"}; blank keeps the usual name."""
    child = serializers.CharField(max_length=40, allow_blank=True, trim_whitespace=True)

    def to_internal_value(self, data):
        names = super().to_internal_value(data)
        unknown = set(names) - {"SHOP", "CYBER", "MPESA"}
        if unknown:
            raise serializers.ValidationError("Name only the shop, services and M-Pesa parts.")
        return {key: value for key, value in names.items() if value}


class StarterService(serializers.Serializer):
    name = serializers.CharField(max_length=180)
    selling_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    # A menu item (MENU) and a kind of room (PER_NIGHT) are set up by the hotel tools, everything else as a service.
    billing_unit = serializers.ChoiceField(choices=[unit for unit, _ in CyberServiceProfile.BILLING_UNITS] + ["MENU", "PER_NIGHT"], default="FIXED")
    requires_job = serializers.BooleanField(default=False)


def seed_starter_records(user, modules, categories, services):
    """The owner's chosen product categories and priced services, so the first sale can happen straight away."""
    from django.utils.text import slugify
    from apps.catalog.models import Category
    if "inventory" in modules:
        for name in dict.fromkeys(name.strip() for name in categories if name.strip()):
            Category.objects.get_or_create(slug=slugify(name)[:50] or "category", defaults={"name": name[:120]})
    from apps.hotel import menu, rooms
    for service in services:
        if service["billing_unit"] == "MENU":
            if "menu" in modules:
                menu.add_item(name=service["name"], price=service["selling_price"])
        elif service["billing_unit"] == "PER_NIGHT":
            if "rooms" in modules:
                rooms.add_room_type(name=service["name"], rate=service["selling_price"])
        elif "services" in modules:
            from apps.cyber.services import create_service
            create_service(user, **service)


def note_kind(organization, categories=(), services=()):
    """A business described under "Other" suggests a new kind for the list; one chosen from the list counts a use."""
    from django.db.models import F
    from .models import BusinessKind
    if organization.sector in profiles.OTHER_SECTORS:
        profiles.record_kind(organization, organization.business_model, organization.business_type, organization.enabled_modules, categories, services)
    elif organization.sector.startswith(profiles.KIND_PREFIX):
        BusinessKind.objects.filter(pk=organization.sector[len(profiles.KIND_PREFIX):]).update(uses=F("uses") + 1)


class BusinessInput(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    business_type = serializers.CharField(max_length=100, allow_blank=True, default="")
    currency = serializers.RegexField(r"^[A-Z]{3}$", default="KES")
    timezone = serializers.CharField(default="Africa/Nairobi")
    country = serializers.RegexField(r"^[A-Z]{2}$", default="KE")
    enabled_modules = serializers.ListField(child=serializers.ChoiceField(choices=MODULES), default=list)
    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Choose a valid IANA time zone.")
        return value

@api_view(["POST"])
@transaction.atomic
def create_business(request):
    from apps.accounting.money_mode import MODES as MONEY_MODES, ONE_DRAWER

    class SetupInput(BusinessInput, ProfileInput):
        business_size = serializers.ChoiceField(choices=list(profiles.SIZES), default="SMALL")
        enabled_modules = serializers.ListField(child=serializers.ChoiceField(choices=MODULES), default=list)
        starter_categories = serializers.ListField(child=serializers.CharField(max_length=120), default=list, max_length=30)
        starter_services = StarterService(many=True, default=list, max_length=40)
        plan = serializers.ChoiceField(choices=["BASIC", "PRO"], default="BASIC")
        branch_name = serializers.CharField(max_length=160, default='Main branch')
        phone = serializers.CharField(max_length=40, allow_blank=True, default="")
        email = serializers.EmailField(allow_blank=True, default="")
        address = serializers.CharField(max_length=500, allow_blank=True, default="")
        opening_cash = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, default=0)
        opening_bank = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, default=0)
        chama = serializers.DictField(required=False, allow_null=True, default=None)  # the chama to set up, when that tool is chosen
        money_mode = serializers.ChoiceField(choices=list(MONEY_MODES), default=ONE_DRAWER)
        structure = serializers.ChoiceField(choices=["SINGLE", "PARTS"], required=False)
        part_names = PartNames(required=False, default=dict)
    form = SetupInput(data=request.data)
    form.is_valid(raise_exception=True)
    values = dict(form.validated_data)
    branch_name = values.pop('branch_name')
    opening_cash, opening_bank = values.pop('opening_cash'), values.pop('opening_bank')
    starter_categories, starter_services = values.pop('starter_categories'), values.pop('starter_services')
    plan_code = values.pop('plan')
    if not request.user.is_superuser:
        # Only what the chosen plan includes: a Basic business never starts with Pro tools.
        from .billing import plan as find_plan
        chosen_plan = find_plan(plan_code)
        beyond = sorted(set(values["enabled_modules"]) - set(chosen_plan.enabled_modules), key=MODULES.index) if chosen_plan else []
        if beyond:
            names = ", ".join(profiles.MODULES[module]["label"] for module in beyond)
            return Response({"enabled_modules": [f"{names} {'is' if len(beyond) == 1 else 'are'} not in the {chosen_plan.name} plan. "
                                                 f"Choose Pro, or leave {'it' if len(beyond) == 1 else 'them'} off."]}, status=400)
    chama = values.pop('chama')
    money_mode = values.pop('money_mode')
    stored = {"money_mode": money_mode}
    chosen_structure = values.pop('structure', None)
    if chosen_structure:
        stored["structure"] = chosen_structure
    names = values.pop('part_names')
    if names:
        stored["part_names"] = names
    from uuid import uuid4
    organization = Organization.objects.create(owner=request.user, slug=f"{slugify(form.validated_data['name'])[:35] or 'business'}-{uuid4().hex[:10]}",
                                               settings=stored, **values)
    Membership.objects.create(user=request.user, organization=organization, role="OWNER")
    # The first month is free on the plan chosen. The platform owner's own businesses are complimentary Pro.
    from .billing import start_trial
    start_trial(organization, plan_code, platform_owner=request.user.is_superuser)
    from apps.core.models import Store, AuditLog
    with organization_context(organization):
        store = Store.objects.create(name=branch_name, currency=organization.currency, timezone=organization.timezone,
                                     phone=organization.phone, email=organization.email, address=organization.address)
        from apps.accounting.ledger import CHART
        from apps.accounting.models import LedgerAccount, CashAccount
        for code, (name, kind, is_cash) in CHART.items():
            LedgerAccount.objects.create(code=code, name=name, kind=kind, is_cash=is_cash)
        CashAccount.objects.create(name='Main till', business_unit='SHOP', payment_method='CASH')
        # Through the cash book, so Money check, the drawer and net worth start from it as well as the books.
        from apps.accounting.services import post as post_cash
        for method, amount in (('CASH', opening_cash), ('BANK', opening_bank)):
            if amount:
                post_cash(unit='SHOP', method=method, amount=amount, kind='OPENING', reference='Starting money entered at setup',
                          key=f'opening:setup-{method.lower()}', user=request.user, branch=store)
        seed_starter_records(request.user, organization.enabled_modules, starter_categories, starter_services)
        note_kind(organization, starter_categories, starter_services)
        if chama and "chama" in organization.enabled_modules:
            # Its own records only: a chama's money never enters the shop's books.
            from apps.chama.api import create_from_setup
            create_from_setup(request.user, chama)
        AuditLog.objects.create(action="BUSINESS_CREATED", object_type="Organization", object_id=str(organization.pk), user=request.user)
    request.session["organization_id"] = organization.pk
    request.session["branch_id"] = store.pk
    return Response(organization_data(organization), status=201)

class RegistrationInput(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    username = serializers.RegexField(r"^[\w.@+-]+$", max_length=150, error_messages={"invalid": "Use only letters, numbers and . @ + - _ in the username, with no spaces."})
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    def validate_phone(self, value):
        digits = re.sub(r"[\s()-]", "", value)
        if not re.fullmatch(r"\+?\d{9,15}", digits):
            raise serializers.ValidationError("Enter a phone number such as 0712 345 678 or +254 712 345 678.")
        return digits

    def validate(self, data):
        if data["password"] != data.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "The two passwords do not match."})
        user = User(username=data["username"], email=data["email"], first_name=data["first_name"], last_name=data["last_name"])
        try:
            password_validation.validate_password(data["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages})
        # One message for a taken username or email, so the form does not reveal who has an account.
        if User.objects.filter(username__iexact=data["username"]).exists() or User.objects.filter(email__iexact=data["email"]).exists():
            raise serializers.ValidationError("Unable to register with these account details. If you already have an account, sign in or reset your password.")
        return data

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
@csrf_protect
@transaction.atomic
def register(request):
    form = RegistrationInput(data=request.data)
    form.is_valid(raise_exception=True)
    values = dict(form.validated_data)
    phone = values.pop("phone")
    user = User.objects.create_user(**values)
    from apps.accounts.models import AccountProfile
    AccountProfile.objects.create(user=user, phone=phone)
    from apps.accounts.device_auth import create_device, set_cookie
    from apps.accounts.device_api import payload
    device, raw = create_device(user)
    request.session.pop('organization_id', None)
    request.session.pop('branch_id', None)
    return set_cookie(Response({**payload(request,device,True), 'next':'/onboarding'}, status=201), raw, device)


# Staff and business settings are managed by the business's owners and administrators.
# An employee is the account the owner gives the people who work in the business; the older roles stay for those who have them.
STAFF_ROLES = ["EMPLOYEE"] + [role for role, _ in Membership.ROLES if role not in {"OWNER", "CUSTOM", "EMPLOYEE"}]

def _require_business_admin(request):
    if not request.organization or not request.membership:
        return Response({"detail": "Select an active business first.", "code": "organization_required"}, status=403)
    if request.membership.role not in {"OWNER", "ADMIN"}:
        return Response({"detail": "Only the business owner or an administrator can manage this."}, status=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        from .billing import state
        if state(request.organization)["ended"]:
            return Response({"detail": "Your subscription has ended, so this is paused. Renew it on the Subscription page to continue.",
                             "code": "subscription_ended"}, status=403)
    return None

def staff_data(membership):
    from apps.accounts.models import LockPin, PagePin
    user = membership.user
    owner = membership.role == "OWNER"
    return {"id": membership.pk, "user_id": user.pk, "username": user.get_username(), "email": user.email,
            "name": user.get_full_name(), "role": membership.role, "status": membership.status,
            "hidden_pages": membership.hidden_pages or [], "open_pages": membership.open_pages or [], "joined_at": membership.joined_at,
            # Whether they have chosen their own password and PINs yet; the owner resets any of them for someone who forgot.
            "setup_pending": membership.setup_pending, "lock_pin_set": LockPin.objects.filter(user=user, page="").exists(),
            "page_pins": [] if owner else sorted(PagePin.objects.filter(user=user).values_list("page", flat=True))}


def hideable_pages(organization):
    """The pages the owner can keep staff out of, for the parts this business runs."""
    from .middleware import effective_modules
    from .permissions import PAGES
    enabled = effective_modules(organization)
    return [{"key": key, "label": label} for key, (label, module, _) in PAGES.items() if (module is None or module in enabled) and key != "investments"]


def work_pages(organization):
    """The pages the owner can give an employee: the work pages of the parts this business runs, investments included."""
    from .middleware import effective_modules
    from .permissions import PAGES, WORK_PAGES
    enabled = effective_modules(organization)
    return [{"key": key, "label": PAGES[key][0]} for key in WORK_PAGES if PAGES[key][1] in enabled]


def _work_pages_value(value):
    from .permissions import WORK_PAGES
    unknown = sorted(set(value) - set(WORK_PAGES))
    if unknown:
        raise serializers.ValidationError(f"An employee cannot be given: {', '.join(unknown)}. Those pages are the owner's.")
    return sorted(set(value))

class StaffInput(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(max_length=150, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, allow_blank=True, default="")
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=STAFF_ROLES, default="EMPLOYEE")
    open_pages = serializers.ListField(child=serializers.CharField(max_length=20), required=False, default=list)

    def validate_open_pages(self, value):
        return _work_pages_value(value)

    def validate(self, data):
        if User.objects.filter(username=data["username"]).exists():
            raise serializers.ValidationError({"username": "This username is already taken."})
        try:
            password_validation.validate_password(data["password"], User(username=data["username"], email=data["email"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages})
        return data

class StaffUpdateInput(serializers.Serializer):
    role = serializers.ChoiceField(choices=STAFF_ROLES, required=False)
    status = serializers.ChoiceField(choices=["ACTIVE", "SUSPENDED"], required=False)
    hidden_pages = serializers.ListField(child=serializers.CharField(max_length=20), required=False)
    open_pages = serializers.ListField(child=serializers.CharField(max_length=20), required=False)

    def validate_open_pages(self, value):
        return _work_pages_value(value)

    def validate_hidden_pages(self, value):
        from .permissions import PAGES
        unknown = sorted(set(value) - set(PAGES))
        if unknown:
            raise serializers.ValidationError(f"There is no such page: {', '.join(unknown)}.")
        return sorted(set(value))

@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def staff(request):
    denied = _require_business_admin(request)
    if denied:
        return denied
    memberships = Membership.objects.filter(organization=request.organization).select_related("user").order_by("joined_at", "pk")
    if request.method == "GET":
        return Response({"roles": STAFF_ROLES, "staff": [staff_data(m) for m in memberships], "pages": hideable_pages(request.organization),
                         "work_pages": work_pages(request.organization)})
    form = StaffInput(data=request.data)
    form.is_valid(raise_exception=True)
    values = dict(form.validated_data)
    role = values.pop("role")
    pages = values.pop("open_pages")
    if (role != "EMPLOYEE" or pages) and request.membership.role != "OWNER":
        return Response({"detail": "Only the business owner adds employees and chooses their pages."}, status=403)
    if role == "ADMIN" and request.membership.role != "OWNER":
        return Response({"detail": "Only the owner can make someone an administrator."}, status=403)
    try:
        with transaction.atomic():
            user = User.objects.create_user(**values)
            # They choose their own password and lock PIN when they first sign in.
            membership = Membership.objects.create(user=user, organization=request.organization, role=role, open_pages=pages, setup_pending=True)
    except DjangoValidationError as exc:
        return Response({"detail": " ".join(exc.messages)}, status=400)
    from apps.core.models import AuditLog
    AuditLog.objects.create(action="STAFF_ADDED", object_type="Membership", object_id=str(membership.pk), user=request.user, after={"username": user.get_username(), "role": role, "open_pages": pages})
    return Response(staff_data(membership), status=201)

@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def staff_member(request, pk):
    denied = _require_business_admin(request)
    if denied:
        return denied
    membership = Membership.objects.filter(organization=request.organization, pk=pk).select_related("user").first()
    if not membership:
        return Response({"detail": "Staff member not found in this business."}, status=404)
    if membership.role == "OWNER" or membership.user_id == request.user.pk:
        return Response({"detail": "The owner's access and your own access cannot be changed here."}, status=400)
    if membership.role == "ADMIN" and request.membership.role != "OWNER":
        return Response({"detail": "Only the owner can change an administrator."}, status=403)
    form = StaffUpdateInput(data=request.data)
    form.is_valid(raise_exception=True)
    if form.validated_data.get("role") == "ADMIN" and request.membership.role != "OWNER":
        return Response({"detail": "Only the owner can make someone an administrator."}, status=403)
    if {"hidden_pages", "open_pages"} & set(form.validated_data) and request.membership.role != "OWNER":
        return Response({"detail": "Only the business owner chooses which pages someone cannot open."}, status=403)
    before = {"role": membership.role, "status": membership.status, "hidden_pages": membership.hidden_pages or [], "open_pages": membership.open_pages or []}
    for field, value in form.validated_data.items():
        setattr(membership, field, value)
    try:
        membership.save()
    except DjangoValidationError as exc:
        return Response({"detail": " ".join(exc.messages)}, status=400)
    from apps.core.models import AuditLog
    AuditLog.objects.create(action="STAFF_CHANGED", object_type="Membership", object_id=str(membership.pk), user=request.user, before=before, after={"role": membership.role, "status": membership.status, "hidden_pages": membership.hidden_pages or [], "open_pages": membership.open_pages or []})
    return Response(staff_data(membership))


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def staff_reset(request, pk):
    """The owner resets what someone forgot. ``what``: "sign_in" gives them a new temporary ``password`` (they choose
    their own password and lock PIN again at their next sign-in, and every device they are on is signed out); "pins"
    clears their private page PINs (``page``, or all of them), so they set new ones the next time they open the page."""
    denied = _require_business_admin(request)
    if denied:
        return denied
    if request.membership.role != "OWNER":
        return Response({"detail": "Only the business owner resets someone's sign-in or PINs."}, status=403)
    membership = Membership.objects.filter(organization=request.organization, pk=pk).select_related("user").first()
    if not membership:
        return Response({"detail": "Staff member not found in this business."}, status=404)
    if membership.role == "OWNER":
        return Response({"detail": "Reset your own PINs in Settings → Lock PIN and private pages."}, status=400)
    from django.utils import timezone
    from apps.accounts.models import DeviceSession, LockPin, PagePin
    from apps.core.models import AuditLog
    user, what = membership.user, request.data.get("what")
    if what == "sign_in":
        password = request.data.get("password") or ""
        try:
            password_validation.validate_password(password, user)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages), "field": "password"}, status=400)
        with transaction.atomic():
            user.set_password(password)
            user.save(update_fields=["password"])
            LockPin.objects.filter(user=user).delete()
            Membership.objects.filter(pk=membership.pk).update(setup_pending=True)
            DeviceSession.objects.filter(user=user, revoked_at=None).update(revoked_at=timezone.now())
    elif what == "pins":
        from apps.accounts.protected_pages import PAGES as PRIVATE
        page = request.data.get("page") or None
        if page and page not in PRIVATE:
            return Response({"detail": "There is no such private page."}, status=400)
        pins = PagePin.objects.filter(user=user)
        (pins.filter(page=page) if page else pins).delete()
    else:
        return Response({"detail": "Choose what to reset: their sign-in or their PINs."}, status=400)
    AuditLog.objects.create(action="STAFF_RESET", object_type="Membership", object_id=str(membership.pk), user=request.user, after={"what": what, "page": request.data.get("page") or ""})
    membership.refresh_from_db()
    return Response(staff_data(membership))

class SettingsInput(serializers.Serializer):
    name = serializers.CharField(max_length=160, required=False)
    business_model = serializers.ChoiceField(choices=list(profiles.BUSINESS_MODELS), required=False)
    sector = serializers.CharField(max_length=40, allow_blank=True, required=False)
    business_size = serializers.ChoiceField(choices=list(profiles.SIZES), required=False)
    business_type = serializers.CharField(max_length=100, allow_blank=True, required=False)
    phone = serializers.CharField(max_length=40, allow_blank=True, required=False)
    email = serializers.EmailField(allow_blank=True, required=False)
    address = serializers.CharField(allow_blank=True, required=False)
    timezone = serializers.CharField(required=False)
    enabled_modules = serializers.ListField(child=serializers.ChoiceField(choices=MODULES), required=False)
    receipt_footer = serializers.CharField(max_length=255, allow_blank=True, required=False)
    money_mode = serializers.ChoiceField(choices=["ONE_DRAWER", "SEPARATE_CASH"], required=False)
    structure = serializers.ChoiceField(choices=["SINGLE", "PARTS"], required=False)
    part_names = PartNames(required=False)
    sale_mpesa_to = serializers.ChoiceField(choices=["AGENT_LINE", "TILL"], required=False)
    validate_timezone = BusinessInput.validate_timezone

def _plan_view(organization):
    """The plan the business is on, for Settings: which tools it includes, and which chosen tools wait for Pro."""
    from .billing import plan_modules, state
    subscription = getattr(organization, "subscription", None)
    included = plan_modules(organization)
    view = state(organization)
    return {"code": view["plan"], "name": "Pro" if subscription and subscription.complimentary else view["plan_name"],
            "complimentary": bool(subscription and subscription.complimentary), "ended": view["ended"],
            "includes": [module for module in MODULES if included is None or module in included],
            "waiting": [module for module in MODULES if included is not None and module in organization.enabled_modules and module not in included]}


def settings_data(organization, store):
    from apps.accounting.money_mode import money_mode, part_names, structure
    from .billing import plan_modules
    own_names = (organization.settings or {}).get("part_names") or {}
    from apps.mpesa.combined import sale_mpesa_to
    return {"money_mode": money_mode(organization), "structure": structure(organization), "part_names": part_names(organization),
            "own_part_names": own_names, "sale_mpesa_to": sale_mpesa_to(organization), "name": organization.name, "business_type": organization.business_type, "business_model": organization.business_model,
            "sector": organization.sector, "business_size": organization.business_size, "phone": organization.phone,
            "email": organization.email, "address": organization.address, "currency": organization.currency,
            "timezone": organization.timezone, "country": organization.country,
            "enabled_modules": organization.enabled_modules, "available_modules": MODULES,
            "plan_modules": sorted(plan_modules(organization)) if plan_modules(organization) is not None else None,
            "plan": _plan_view(organization),
            "receipt_footer": store.receipt_footer if store else "", "logo_url": public_logo_path(organization),
            "logo_dark_url": public_logo_path(organization, "logo_dark")}

@api_view(["GET", "PATCH"])
@permission_classes([permissions.IsAuthenticated])
def business_settings(request):
    denied = _require_business_admin(request)
    if denied:
        return denied
    from apps.core.models import AuditLog, Store
    organization = request.organization
    store = request.store or Store.objects.order_by("created_at", "pk").first()
    if request.method == "GET":
        return Response(settings_data(organization, store))
    form = SettingsInput(data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    values = dict(form.validated_data)
    profile_fields = {"business_model", "sector", "business_size", "business_type", "enabled_modules"}
    if profile_fields & set(values):
        # A change to what the business does or which tools it uses is checked against the whole profile.
        current = {field: getattr(organization, field) for field in profile_fields}
        if "business_model" in values and "sector" not in values and values["business_model"] != organization.business_model:
            current["sector"] = ""  # the old kind of business belongs to the old model
        profile = ProfileInput(data={**current, **{k: v for k, v in values.items() if k in profile_fields}}, context={"current_sector": organization.sector})
        profile.is_valid(raise_exception=True)
        values.update(profile.validated_data)
        from .billing import plan_modules
        included = plan_modules(organization)
        # Tools already chosen before (for example at set-up) are kept; newly ticked ones must be in the plan.
        beyond = sorted(set(values["enabled_modules"]) - set(organization.enabled_modules) - included, key=MODULES.index) if included is not None else []
        if beyond:
            names = ", ".join(profiles.MODULES[module]["label"] for module in beyond)
            return Response({"enabled_modules": [f"{names} {'needs' if len(beyond) == 1 else 'need'} the Pro plan. Upgrade on the Subscription page to use {'it' if len(beyond) == 1 else 'them'}."]}, status=400)
    before = settings_data(organization, store)
    footer = values.pop("receipt_footer", None)
    # How the money is kept, whether the business has parts and what they are called live in the business's settings.
    kept = {key: values.pop(key) for key in ("money_mode", "structure", "part_names", "sale_mpesa_to") if key in values}
    with transaction.atomic():
        for field, value in values.items():
            setattr(organization, field, value)
        if kept:
            organization.settings = {**(organization.settings or {}), **kept}
            values.update(kept)  # for the audit below
        organization.save()
        if "timezone" in values:
            Store.objects.update(timezone=organization.timezone)
        if store and footer is not None:
            store.receipt_footer = footer
            store.save(update_fields=["receipt_footer", "updated_at"])
        after = settings_data(organization, store)
        if before["sector"] != after["sector"] or (organization.sector in profiles.OTHER_SECTORS and before["business_type"] != after["business_type"]):
            note_kind(organization)
        AuditLog.objects.create(action="BUSINESS_SETTINGS_CHANGED", object_type="Organization", object_id=str(organization.pk), user=request.user,
                                before={k: before[k] for k in values if k in before}, after={k: after[k] for k in values if k in after})
    return Response(after)


class PublicReceiptThrottle(AnonRateThrottle):
    scope = "public_receipt"
    rate = "120/hour"


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
@throttle_classes([PublicReceiptThrottle])
def public_receipt(request, token):
    """The customer's receipt behind a private share link; no account needed."""
    from apps.commerce.receipts import public_receipt as load
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        return Response({"detail": "This receipt link is not valid."}, status=404)
    receipt = load(token, request)
    if not receipt:
        return Response({"detail": "This receipt link is not valid or has been turned off by the business."}, status=404)
    response = Response(receipt)
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex"
    return response


def public_logo(request, name):
    """Business logos are public by design: they print on receipts sent to customers."""
    from django.http import FileResponse, Http404
    if not re.fullmatch(r"[0-9a-f]{32}\.png", name):
        raise Http404
    from django.db.models import Q
    path = f"logos/{name}"
    organization = Organization.objects.filter(Q(logo=path) | Q(logo_dark=path), active=True).first()
    if not organization:
        raise Http404
    stored = organization.logo if organization.logo.name == path else organization.logo_dark
    try:
        response = FileResponse(stored.open("rb"), content_type="image/png")
    except FileNotFoundError:
        raise Http404
    response["Cache-Control"] = "public, max-age=86400"
    return response


@api_view(["POST", "DELETE"])
@permission_classes([permissions.IsAuthenticated])
def business_logo(request):
    denied = _require_business_admin(request)
    if denied:
        return denied
    from apps.core.models import AuditLog
    from .logos import process
    organization = request.organization
    old = [f.name for f in (organization.logo, organization.logo_dark) if f]
    if request.method == "POST":
        light, dark = process(request.FILES.get("logo"))
        organization.logo.save("logo.png", light, save=False)
        organization.logo_dark.save("logo.png", dark, save=False)
    else:
        organization.logo = ""
        organization.logo_dark = ""
    organization.save(update_fields=["logo", "logo_dark"])
    for name in old:
        organization.logo.storage.delete(name)
    AuditLog.objects.create(action="BUSINESS_LOGO_CHANGED", object_type="Organization", object_id=str(organization.pk),
                            user=request.user, before={"logo": old}, after={"logo": organization.logo.name if organization.logo else ""})
    return Response(organization_data(organization))
