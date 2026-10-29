"""Subscription billing for business owners, the M-Pesa callback, and the platform owner's subscription administration."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, OuterRef, Subquery, Sum
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import billing
from .context import organization_context
from .models import MODULES, Membership, Organization, OrganizationSubscription, PlanPrice, SubscriptionPayment, SubscriptionPlan

PLAN_FEATURES = {"inventory": "Products & stock", "services": "Services & jobs", "pos": "Point of sale & receipts",
                 "customers": "Customers & credit", "expenses": "Expenses", "mpesa": "M-Pesa agency",
                 "reports": "Profit & loss, balance sheet and reports", "locations": "Shelves & locations",
                 "staff": "Staff accounts & roles", "branches": "More than one branch", "chama": "Chama management",
                 "investments": "Investments (MMF)", "menu": "Menu & kitchen for eateries", "rooms": "Rooms, bookings & guests' bills"}


def plan_data(plan, organization=None, sector=None):
    """A plan as shown to a business: ``price`` is what it costs that business (or that kind of business), and
    ``price_from`` the lowest it costs any kind, for pages shown before the kind is known."""
    price, source = billing.price_for(plan, organization, sector)
    kind_prices = [p.price for p in plan.prices.all() if p.organization_id is None]
    return {"id": plan.pk, "code": plan.code, "name": plan.name, "price": str(price), "price_source": source,
            "standard_price": str(plan.price), "price_from": str(min([plan.price, *kind_prices])),
            "prices_vary": any(value != plan.price for value in kind_prices), "currency": plan.currency,
            "period_days": plan.period_days, "description": plan.description, "active": plan.active,
            "enabled_modules": plan.enabled_modules, "features": [PLAN_FEATURES[m] for m in MODULES if m in plan.enabled_modules],
            "feature_names": {m: PLAN_FEATURES[m] for m in MODULES if m in plan.enabled_modules}}


def payment_data(payment):
    return {"id": payment.pk, "plan": payment.plan.name, "plan_code": payment.plan.code, "amount": str(payment.amount),
            "currency": payment.currency, "method": payment.method, "phone": payment.phone, "status": payment.status,
            "status_detail": payment.status_detail, "receipt_number": payment.receipt_number,
            "created_at": payment.created_at, "paid_at": payment.paid_at, "period_ends_at": payment.period_ends_at}


def plans():
    return SubscriptionPlan.objects.filter(active=True).exclude(code="").prefetch_related("prices").order_by("sort_order", "price")


def _owner_or_admin(request):
    if not request.organization or not request.membership:
        return Response({"detail": "Select an active business first.", "code": "organization_required"}, status=403)
    if request.membership.role not in {"OWNER", "ADMIN"}:
        return Response({"detail": "Only the business owner or an administrator can manage the subscription."}, status=403)
    return None


def _default_phone(request):
    profile = getattr(request.user, "account_profile", None)
    return (profile.phone if profile else "") or request.organization.phone


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_plans(request):
    """The plans on offer, for registration and the public pricing section."""
    sector = str(request.query_params.get("sector", ""))[:40]
    return Response({"plans": [plan_data(p, sector=sector) for p in plans()], "trial_days": billing.TRIAL_DAYS})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def subscription(request):
    denied = _owner_or_admin(request)
    if denied:
        return denied
    payments = SubscriptionPayment.objects.filter(organization=request.organization).select_related("plan")[:20]
    return Response({"subscription": billing.state(request.organization), "plans": [plan_data(p, request.organization) for p in plans()],
                     "payments": [payment_data(p) for p in payments], "payment_methods": ["MPESA"] if billing.mpesa_configured() else [],
                     "simulated_payments": billing.mpesa_mode() == "simulate" and billing.mpesa_configured(),
                     "phone": _default_phone(request)})


class PayInput(serializers.Serializer):
    plan = serializers.CharField()
    phone = serializers.CharField(max_length=20)
    method = serializers.ChoiceField(choices=["MPESA"], default="MPESA")

    def validate_phone(self, value):
        try:
            return billing.normalize_phone(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error))

    def validate_plan(self, value):
        plan = plans().filter(code=value).first()
        if not plan:
            raise serializers.ValidationError("Choose one of the plans shown.")
        return plan


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def pay(request):
    denied = _owner_or_admin(request)
    if denied:
        return denied
    if billing.state(request.organization)["complimentary"]:
        return Response({"detail": "This business is on a free platform plan and never needs payment."}, status=400)
    form = PayInput(data=request.data)
    form.is_valid(raise_exception=True)
    recent = timezone.now() - timedelta(minutes=2)
    if SubscriptionPayment.objects.filter(organization=request.organization, status="PENDING", created_at__gte=recent).exists():
        return Response({"detail": "A payment prompt was sent less than two minutes ago. Complete or cancel it on your phone first."}, status=409)
    plan = form.validated_data["plan"]
    payment = SubscriptionPayment.objects.create(organization=request.organization, plan=plan, amount=billing.price_for(plan, request.organization)[0], currency=plan.currency,
                                                 method="MPESA", phone=form.validated_data["phone"], requested_by=request.user)
    try:
        billing.request_payment(payment)
    except billing.PaymentUnavailable as error:
        billing.mark_failed(payment, str(error))
        return Response({"detail": str(error), "payment": payment_data(payment)}, status=503)
    return Response(payment_data(payment), status=201)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def payment_status(request, pk):
    denied = _owner_or_admin(request)
    if denied:
        return denied
    payment = SubscriptionPayment.objects.select_related("plan").filter(pk=pk, organization=request.organization).first()
    if not payment:
        return Response({"detail": "Payment not found."}, status=404)
    payment = billing.check_pending(payment)
    request.organization.refresh_from_db()
    return Response({**payment_data(payment), "subscription": billing.state(Organization.objects.select_related("subscription__plan").get(pk=payment.organization_id))})


@csrf_exempt
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def mpesa_callback(request, token):
    """Safaricom posts the STK result here. The secret in the address and the pending checkout identify the payment."""
    import hmac
    expected = getattr(settings, "MPESA_CALLBACK_TOKEN", "")
    if not expected or not hmac.compare_digest(str(token), expected):
        return Response({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
    result = (request.data.get("Body") or {}).get("stkCallback") or {}
    payment = SubscriptionPayment.objects.filter(checkout_request_id=result.get("CheckoutRequestID") or "-").first()
    if payment and payment.status == "PENDING":
        billing.apply_result(payment, result.get("ResultCode"), result.get("ResultDesc", ""), result.get("CallbackMetadata"))
    return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


# --- Platform owner --------------------------------------------------------------------------------------------

def _platform_admin(request):
    if not (request.user.is_authenticated and request.user.is_active and request.user.is_superuser):
        return Response({"detail": "Only the platform administrator can open this."}, status=403)
    return None


def _owner(organization):
    user = organization.owner
    if not user:
        return {"name": "", "username": "", "email": "", "phone": ""}
    profile = getattr(user, "account_profile", None)
    return {"name": user.get_full_name(), "username": user.username, "email": user.email, "phone": profile.phone if profile else ""}


def kind_label(sector_id):
    """The name of a kind of business, built-in or added by an owner (listed or not)."""
    from . import business_profiles as profiles
    found = profiles.find_sector(sector_id, also=sector_id) if sector_id else None
    return found[1]["label"] if found else ""


def kinds():
    """Every kind of business a plan can be priced for: the built-in ones, then those owners added, by model."""
    from . import business_profiles as profiles
    from .models import BusinessKind
    added = {model: [] for model in profiles.SECTORS}
    for kind in BusinessKind.objects.order_by("label"):
        added[kind.business_model].append({"id": kind.sector_id, "label": kind.label, "model": kind.business_model,
                                           "listed": kind.status == "LISTED"})
    return [row for model, sectors in profiles.SECTORS.items()
            for row in [{"id": s["id"], "label": s["label"], "model": model, "listed": True} for s in sectors] + added[model]]


def pricing(organization):
    """How the business is priced: the kind it is billed as, and what each plan costs it and why."""
    sector = billing.billing_sector(organization)
    rows = []
    for plan in SubscriptionPlan.objects.exclude(code="").order_by("sort_order", "price"):
        price, source = billing.price_for(plan, organization)
        own = PlanPrice.objects.filter(plan=plan, organization=organization).first()
        rows.append({"plan": plan.code, "plan_name": plan.name, "price": str(price), "source": source, "currency": plan.currency,
                     "kind_price": str(billing.price_for(plan, sector=sector)[0]), "note": own.note if own else ""})
    return {"billing_sector": sector, "billing_kind": kind_label(sector), "sector": organization.sector,
            "kind": kind_label(organization.sector), "kind_changed": bool(sector and organization.sector and sector != organization.sector),
            "plans": rows}


def business_row(organization):
    view = billing.state(organization)
    return {"id": organization.pk, "name": organization.name, "business_type": organization.business_type,
            "business_model": organization.business_model, "phone": organization.phone, "email": organization.email,
            "country": organization.country, "created_at": organization.created_at, "active": organization.active,
            "owner": _owner(organization), "subscription": view,
            "members": getattr(organization, "member_count", None) or 0,
            "total_paid": str(getattr(organization, "total_paid", None) or Decimal("0")),
            "last_paid_at": getattr(organization, "last_paid_at", None)}


def _businesses():
    # Subqueries, so counting members and adding up payments never multiply each other.
    paid = SubscriptionPayment.objects.filter(organization=OuterRef("pk"), status="PAID").values("organization")
    members = Membership.objects.filter(organization=OuterRef("pk"), status="ACTIVE").values("organization")
    return (Organization.objects.select_related("owner__account_profile", "subscription__plan")
            .annotate(member_count=Subquery(members.annotate(n=Count("pk")).values("n")[:1]),
                      total_paid=Subquery(paid.annotate(v=Sum("amount")).values("v")[:1]),
                      last_paid_at=Subquery(paid.annotate(v=Max("paid_at")).values("v")[:1]))
            .order_by("-created_at"))


def platform_summary(rows):
    """Totals across all businesses (``rows`` from business_row): subscriptions by state and plan, and revenue."""
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    paid = SubscriptionPayment.objects.filter(status="PAID")
    count = lambda test: sum(1 for row in rows if test(row["subscription"]))
    return {"businesses": len(rows), "trial": count(lambda s: s["status"] == "TRIAL"),
            "paying": count(lambda s: s["status"] == "ACTIVE" and s["plan"] and not s["complimentary"] and not s["ended"]),
            "ended": count(lambda s: s["ended"]), "expiring_soon": count(lambda s: s.get("expiring_soon")),
            "complimentary": count(lambda s: s["complimentary"]),
            "switched_off": sum(1 for row in rows if not row["active"]),
            "by_plan": {p.code: count(lambda s, code=p.code: s["plan"] == code and not s["ended"]) for p in plans()},
            "revenue_this_month": str(paid.filter(paid_at__gte=month_start).aggregate(v=Sum("amount"))["v"] or Decimal("0")),
            "revenue_total": str(paid.aggregate(v=Sum("amount"))["v"] or Decimal("0")),
            "currency": "KES", "mpesa_mode": billing.mpesa_mode(), "mpesa_ready": billing.mpesa_configured()}


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def platform_overview(request):
    denied = _platform_admin(request)
    if denied:
        return denied
    rows = [business_row(org) for org in _businesses()]
    summary = platform_summary(rows)
    recent = SubscriptionPayment.objects.select_related("plan", "organization")[:15]
    return Response({"summary": summary, "businesses": rows,
                     "recent_payments": [{**payment_data(p), "business": p.organization.name, "business_id": p.organization_id} for p in recent],
                     "plans": [admin_plan_data(p) for p in SubscriptionPlan.objects.exclude(code="").prefetch_related("prices").order_by("sort_order", "price")],
                     "kinds": kinds()})


def admin_plan_data(plan):
    """A plan with the prices set for each kind of business and how many businesses have a price of their own."""
    rows = plan.prices.all()
    return {**plan_data(plan), "price": str(plan.price), "price_source": "standard",
            "kind_prices": {p.sector: str(p.price) for p in rows if p.organization_id is None},
            "business_prices": sum(1 for p in rows if p.organization_id is not None)}


class BusinessSubscriptionInput(serializers.Serializer):
    plan = serializers.CharField(required=False)
    status = serializers.ChoiceField(choices=["TRIAL", "ACTIVE", "SUSPENDED", "CANCELLED"], required=False)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    extend_days = serializers.IntegerField(required=False, min_value=1, max_value=3650)
    complimentary = serializers.BooleanField(required=False)
    active = serializers.BooleanField(required=False)
    # The kind of business its plans are priced for, and its own prices by plan code (null goes back to the kind's price).
    billing_sector = serializers.CharField(max_length=40, required=False)
    prices = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1"), allow_null=True), required=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_billing_sector(self, value):
        if not kind_label(value):
            raise serializers.ValidationError("Choose a kind of business.")
        return value

    def validate_prices(self, value):
        unknown = set(value) - set(SubscriptionPlan.objects.exclude(code="").values_list("code", flat=True))
        if unknown:
            raise serializers.ValidationError("Choose one of the plans.")
        return value


class ManualPaymentInput(serializers.Serializer):
    plan = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    receipt_number = serializers.CharField(max_length=40, required=False, allow_blank=True)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


def _audit(organization, user, action, before, after):
    from apps.core.models import AuditLog
    with organization_context(organization):
        # The platform administrator is not a member of the business, so they are named in the record instead of linked.
        AuditLog.objects.create(action=action, object_type="OrganizationSubscription", object_id=str(organization.pk), user=None,
                                before=before, after={**after, "by_platform_admin": user.username})


def _plain(view):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in view.items()}


def _priced(organization):
    """The subscription with what the business is billed as, for the history."""
    own = {p.plan.code: str(p.price) for p in PlanPrice.objects.filter(organization=organization).select_related("plan")}
    return {**_plain(billing.state(organization)), "billing_sector": billing.billing_sector(organization), "own_prices": own}


@api_view(["GET", "PATCH", "POST", "DELETE"])
@permission_classes([permissions.IsAuthenticated])
def platform_business(request, pk):
    """GET the business's subscription and payments; PATCH to change plan, status, dates or switch the business off and on;
    POST to record a manual payment; DELETE (with the business name typed again and the administrator's protected pages
    password) to remove a switched-off business for good."""
    denied = _platform_admin(request)
    if denied:
        return denied
    organization = _businesses().filter(pk=pk).first()
    if not organization:
        return Response({"detail": "Business not found."}, status=404)
    if request.method == "GET":
        payments = SubscriptionPayment.objects.filter(organization=organization).select_related("plan")
        return Response({**business_row(organization), "pricing": pricing(organization), "payments": [payment_data(p) for p in payments]})
    if request.method == "DELETE":
        return _delete_business(request, organization)
    before = _priced(organization)
    if request.method == "POST":
        form = ManualPaymentInput(data=request.data)
        form.is_valid(raise_exception=True)
        plan = SubscriptionPlan.objects.filter(code=form.validated_data["plan"]).first()
        if not plan:
            return Response({"plan": ["Choose a plan."]}, status=400)
        payment = SubscriptionPayment.objects.create(organization=organization, plan=plan, amount=form.validated_data["amount"],
                                                     currency=plan.currency, method="MANUAL", requested_by=request.user,
                                                     status_detail=form.validated_data.get("note", "")[:255])
        billing.mark_paid(payment, receipt_number=form.validated_data.get("receipt_number", ""))
        organization = _businesses().get(pk=pk)
        _audit(organization, request.user, "SUBSCRIPTION_PAYMENT_RECORDED", before, _priced(organization))
        return Response(business_row(organization), status=201)
    form = BusinessSubscriptionInput(data=request.data)
    form.is_valid(raise_exception=True)
    values = form.validated_data
    was_active = organization.active
    with transaction.atomic():
        subscription = OrganizationSubscription.objects.select_for_update().get(organization=organization)
        if "plan" in values:
            plan = SubscriptionPlan.objects.filter(code=values["plan"]).first()
            if not plan:
                return Response({"plan": ["Choose a plan."]}, status=400)
            subscription.plan = plan
        for field in ("status", "complimentary"):
            if field in values:
                setattr(subscription, field, values[field])
        if "ends_at" in values:
            subscription.ends_at = values["ends_at"]
        if "active" in values and values["active"] != organization.active:
            if not values["active"] and Membership.objects.filter(organization=organization, user=request.user).exists():
                return Response({"detail": "You work in this business, so you cannot switch it off from here."}, status=400)
            Organization.objects.filter(pk=organization.pk).update(active=values["active"])
        if "billing_sector" in values:
            subscription.billing_sector = values["billing_sector"]
        for code, price in values.get("prices", {}).items():
            plan = SubscriptionPlan.objects.get(code=code)
            if price is None:
                PlanPrice.objects.filter(plan=plan, organization=organization).delete()
            else:
                PlanPrice.objects.update_or_create(plan=plan, organization=organization,
                                                   defaults={"price": price, "note": values.get("note", "")[:255]})
        if values.get("extend_days"):
            base = max(subscription.ends_at or timezone.now(), timezone.now())
            subscription.ends_at = base + timedelta(days=values["extend_days"])
            if subscription.status not in billing.RUNNING:
                subscription.status = "ACTIVE"
        subscription.save()
    organization = _businesses().get(pk=pk)
    if organization.active != was_active:
        _audit(organization, request.user, "BUSINESS_ACTIVATED" if values["active"] else "BUSINESS_DEACTIVATED",
               {"active": was_active, "note": values.get("note", "")}, {"active": organization.active})
    if set(values) - {"active", "note"}:
        _audit(organization, request.user, "SUBSCRIPTION_CHANGED", {**before, "note": values.get("note", "")}, _priced(organization))
    return Response({**business_row(organization), "pricing": pricing(organization)})


def _delete_business(request, organization):
    from .removal import delete_business
    if organization.active:
        return Response({"detail": "Switch the business off first. Only a switched-off business can be deleted."}, status=400)
    if Membership.objects.filter(organization=organization, user=request.user).exists():
        return Response({"detail": "You work in this business, so you cannot delete it from here."}, status=400)
    if (request.data.get("confirm_name") or "").strip() != organization.name.strip():
        return Response({"confirm_name": ["Type the business name exactly as shown to confirm."]}, status=400)
    from apps.accounts.protected_pages import confirm
    with transaction.atomic():
        refusal = confirm(request, request.data.get("password", ""))
    if refusal:
        return refusal
    removed = delete_business(organization)
    return Response({"deleted": organization.name, "records": sum(removed.values())})


class PlanInput(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1"), required=False)
    description = serializers.CharField(max_length=255, allow_blank=True, required=False)
    active = serializers.BooleanField(required=False)
    enabled_modules = serializers.ListField(child=serializers.ChoiceField(choices=MODULES), required=False, allow_empty=False)
    # The price for each kind of business, by kind id; null goes back to the standard price.
    kind_prices = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1"), allow_null=True), required=False)

    def validate_kind_prices(self, value):
        unknown = [sector for sector in value if not kind_label(sector)]
        if unknown:
            raise serializers.ValidationError(f"Unknown kind of business: {', '.join(unknown)}.")
        return value


@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def platform_plan(request, pk):
    denied = _platform_admin(request)
    if denied:
        return denied
    plan = SubscriptionPlan.objects.filter(pk=pk).first()
    if not plan:
        return Response({"detail": "Plan not found."}, status=404)
    form = PlanInput(data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    values = dict(form.validated_data)
    kind_prices = values.pop("kind_prices", {})
    for field, value in values.items():
        setattr(plan, field, value)
    plan.save()
    for sector, price in kind_prices.items():
        if price is None:
            PlanPrice.objects.filter(plan=plan, sector=sector, organization__isnull=True).delete()
        else:
            PlanPrice.objects.update_or_create(plan=plan, sector=sector, organization=None, defaults={"price": price})
    return Response(admin_plan_data(SubscriptionPlan.objects.prefetch_related("prices").get(pk=plan.pk)))


# --- Kinds of business added by owners ----------------------------------------------------------------------------

def kind_data(kind):
    from . import business_profiles as profiles
    return {"id": kind.pk, "sector_id": kind.sector_id, "business_model": kind.business_model, "label": kind.label, "hint": kind.hint,
            "keywords": kind.keywords, "modules": kind.modules, "categories": kind.categories, "services": kind.services,
            "status": kind.status, "uses": kind.uses, "created_by": kind.created_by.name if kind.created_by else "",
            "created_at": kind.created_at, "allowed_modules": profiles.BUSINESS_MODELS[kind.business_model]["modules"]}


class KindInput(serializers.Serializer):
    label = serializers.CharField(max_length=100, required=False)
    hint = serializers.CharField(max_length=160, allow_blank=True, required=False)
    keywords = serializers.CharField(max_length=255, allow_blank=True, required=False)
    modules = serializers.ListField(child=serializers.ChoiceField(choices=MODULES), required=False)
    categories = serializers.ListField(child=serializers.CharField(max_length=120), max_length=30, required=False)
    status = serializers.ChoiceField(choices=["SUGGESTED", "LISTED", "HIDDEN"], required=False)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def platform_kinds(request):
    """Kinds of business owners described under "Other", newest first, for the platform owner to list or hide."""
    denied = _platform_admin(request)
    if denied:
        return denied
    from .models import BusinessKind
    return Response([kind_data(kind) for kind in BusinessKind.objects.select_related("created_by")])


@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def platform_kind(request, pk):
    """Tidy a suggested kind (name, description, search words, usual tools, categories) and list or hide it."""
    denied = _platform_admin(request)
    if denied:
        return denied
    from . import business_profiles as profiles
    from .models import BusinessKind
    kind = BusinessKind.objects.select_related("created_by").filter(pk=pk).first()
    if not kind:
        return Response({"detail": "Kind of business not found."}, status=404)
    form = KindInput(data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    values = dict(form.validated_data)
    if "label" in values:
        values["label"] = " ".join(values["label"].split())
        values["key"] = profiles.kind_key(values["label"])
        if not values["key"]:
            return Response({"label": ["Enter a name."]}, status=400)
        if BusinessKind.objects.filter(business_model=kind.business_model, key=values["key"]).exclude(pk=kind.pk).exists():
            return Response({"label": ["Another kind of business already has this name."]}, status=400)
    if "modules" in values:
        problems = profiles.module_problems(kind.business_model, values["modules"])
        if problems:
            return Response({"modules": [" ".join(problems)]}, status=400)
        values["modules"] = sorted(set(values["modules"]), key=list(profiles.MODULES).index)
    if "categories" in values:
        values["categories"] = list(dict.fromkeys(name.strip() for name in values["categories"] if name.strip()))
    for field, value in values.items():
        setattr(kind, field, value)
    kind.save()
    return Response(kind_data(kind))
