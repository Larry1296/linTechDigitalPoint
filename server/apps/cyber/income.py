"""Income per Cyber service, and each service's price options.

A service (printing, KRA PIN registration…) is a service product; each of its price options ("Single side",
"Both sides", "Bulk 50+ pages") is one of its variants with a Cyber profile: its own price, unit, lowest price,
cost and whether its amount varies. Recording income goes through the same job and sale as the Service Desk (a
job created and completed in one step), so receipts, materials used, profit and the books stay as for any job.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from apps.catalog.models import Category, Product, ProductVariant, check_price_range
from apps.commerce.models import Payment
from apps.core.models import AuditLog
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.permissions import has_business_permission
from .models import CyberJobLine, CyberServiceProfile
from .services import add_price_option, complete_job, create_job, create_service, services_category

ZERO = Decimal("0")
CENT = Decimal("0.01")
UNITS = [value for value, _ in CyberServiceProfile.BILLING_UNITS]


def _require(request, *permissions):
    if not all(has_business_permission(request.user, p) for p in permissions):
        raise PermissionDenied()


def _earned():
    """Lines of completed jobs whose sale still stands (a fully returned sale is not income)."""
    return CyberJobLine.objects.filter(job__status="COMPLETED", job__sale__status="COMPLETED")


def _periods():
    today = timezone.localdate()
    # Revenue since the start leads; there is no "today" figure (the owner follows where income has reached).
    return {"all": date(1900, 1, 1), "month": today.replace(day=1), "week": today - timedelta(days=today.weekday())}


def _by_variant(rows):
    """{period: {variant_id: {"amount", "units", "times"}}} in one query per period."""
    result = {}
    for name, start in _periods().items():
        result[name] = {row["variant_id"]: {"amount": row["amount"], "units": row["units"], "times": row["times"]}
                        for row in rows.filter(job__completed_at__date__gte=start).values("variant_id")
                        .annotate(amount=Sum("line_total"), units=Sum("quantity"), times=Count("id"))}
    return result


def _sum(sums, period, variant_ids):
    empty = {"amount": ZERO, "units": ZERO, "times": 0}
    rows = [sums[period].get(v, empty) for v in variant_ids]
    return {"amount": sum((r["amount"] for r in rows), ZERO), "units": sum((r["units"] for r in rows), ZERO),
            "times": sum((r["times"] for r in rows), 0)}


def _option(profile, sums, show_cost):
    variant = profile.variant
    row = {"id": profile.pk, "name": variant.name, "price": variant.selling_price, "minimum_price": variant.minimum_price,
           "billing_unit": profile.billing_unit, "price_varies": profile.price_varies, "active": profile.active and variant.active}
    if show_cost:
        row["cost"] = variant.service_cost
    row.update({period: _sum(sums, period, [variant.pk]) for period in _periods()})
    return row


def groups():
    """Service groups in the order they were made: sub-categories of Services, each with its own sub-groups."""
    root = services_category()
    tops = list(Category.objects.filter(parent=root, active=True).order_by("pk"))
    children = defaultdict(list)
    for child in Category.objects.filter(parent__in=tops, active=True).order_by("pk"):
        children[child.parent_id].append({"id": child.pk, "name": child.name})
    return [{"id": top.pk, "name": top.name, "subgroups": children[top.pk]} for top in tops]


def _place(category, root_id):
    """(group, subgroup) of a service's category; (None, None) when it is directly under Services or elsewhere."""
    if not category or category.pk == root_id:
        return None, None
    if category.parent_id == root_id:
        return {"id": category.pk, "name": category.name}, None
    parent = category.parent
    if parent and parent.parent_id == root_id:
        return {"id": parent.pk, "name": parent.name}, {"id": category.pk, "name": category.name}
    return None, None


def _group_category(category_id):
    """A group or sub-group of Services, chosen for a service; empty means straight under Services."""
    root = services_category()
    if not category_id:
        return root
    category = Category.objects.filter(pk=category_id, active=True).select_related("parent").first()
    if not category or not (category.parent_id == root.pk or (category.parent and category.parent.parent_id == root.pk)):
        raise ValidationError("Choose one of your service groups.")
    return category


def _services(request, product_id=None, removed=False):
    root_id = services_category().pk
    profiles = CyberServiceProfile.objects.select_related("variant__product__category__parent").order_by("variant__product__name", "variant__pk")
    if not removed:
        profiles = profiles.filter(removed_at__isnull=True)
    if product_id:
        profiles = profiles.filter(variant__product_id=product_id)
    show_cost = has_business_permission(request.user, "accounting.view_profit")
    sums = _by_variant(_earned())
    grouped = defaultdict(list)
    for profile in profiles:
        grouped[profile.variant.product].append(profile)
    rows = []
    for product, options in grouped.items():
        group, subgroup = _place(product.category, root_id)
        row = {"id": product.pk, "name": product.name, "notes": options[0].notes, "group": group, "subgroup": subgroup,
               "active": product.active and any(p.active and p.variant.active for p in options),
               "removed": all(p.removed_at for p in options),
               "options": [_option(p, sums, show_cost) for p in options]}
        row.update({period: _sum(sums, period, [p.variant_id for p in options]) for period in _periods()})
        rows.append(row)
    return rows


def _unit(unit):
    return {"PER_PAGE": "page", "PER_COPY": "copy", "PER_SHEET": "sheet", "PER_DOCUMENT": "document", "PER_HOUR": "hour",
            "PER_ITEM": "item"}.get(unit, "")


class NewServiceInput(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    option_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="Standard")
    price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=ZERO)
    billing_unit = serializers.ChoiceField(choices=UNITS, default="FIXED")
    price_varies = serializers.BooleanField(default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


@api_view(["GET", "POST"])
@permission_classes([HasLinTechPermission])
def income_by_service(request):
    _require(request, "cyber.view_cyberjob")
    if request.method == "POST":
        _require(request, "cyber.add_cyberserviceprofile", "catalog.add_product")
        form = NewServiceInput(data=request.data)
        form.is_valid(raise_exception=True)
        d = form.validated_data
        name = " ".join(d["name"].split())
        if CyberServiceProfile.objects.filter(variant__product__name__iexact=name).exists():
            raise ValidationError(f"You already have a service called {name}. Add a price option to it instead.")
        with transaction.atomic():
            profile = create_service(request.user, name, d["price"], billing_unit=d["billing_unit"], notes=d["notes"],
                                     category=_group_category(d.get("category_id")))
            profile.price_varies = d["price_varies"]
            profile.save(update_fields=["price_varies", "updated_at"])
            option = (d["option_name"] or "").strip()
            if option and option != profile.variant.name:
                ProductVariant.objects.filter(pk=profile.variant_id).update(name=option[:120])
        return Response(_services(request, profile.variant.product_id)[0], status=201)
    rows = _services(request, removed=True)  # deleted services' past income still counts in the totals
    return Response({"services": [r for r in rows if not r["removed"]], "groups": groups(),
                     "totals": {period: sum((r[period]["amount"] for r in rows), ZERO) for period in _periods()}})


class LineInput(serializers.Serializer):
    option_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=CENT, required=False, allow_null=True)


class PaymentInput(serializers.Serializer):
    payment_method = serializers.ChoiceField(choices=["CASH", "MPESA", "BANK", "OTHER"])
    payment_reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    customer_name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


class IncomeInput(LineInput, PaymentInput):
    """One service on its own page."""


class VisitInput(PaymentInput):
    """Everything one customer had done and paid for at once: one receipt, one payment."""
    lines = LineInput(many=True, allow_empty=False)


def _job_lines(request, lines, product=None):
    """The job lines for what was done, each checked against its price option's rules."""
    job_lines = []
    for line in lines:
        options = CyberServiceProfile.objects.select_related("variant__product").filter(pk=line["option_id"])
        if product:
            options = options.filter(variant__product=product)
        profile = options.first()
        if not profile or not (profile.active and profile.variant.active and profile.variant.product.active):
            raise ValidationError("Choose one of the service's price options." if product else "One of the services chosen is no longer offered.")
        amount, name = line.get("amount"), profile.variant.product.name
        if amount is None and (profile.price_varies or profile.variant.selling_price <= 0):
            raise ValidationError(f"Enter the amount charged for {name}.")
        if amount is not None:
            try:
                _check_amount(request.user, profile, line["quantity"], amount)
            except ValidationError as exc:
                raise ValidationError(f"{name}: {exc.detail[0]}") from exc
        job_lines.append(_line(profile, line["quantity"], amount))
    return job_lines


def _record(request, lines, d, product=None):
    """Records what was done as one job, sale and payment."""
    _require(request, "cyber.add_cyberjob", "cyber.complete_cyber_job")
    job_lines = _job_lines(request, lines, product)
    key = f"cyber-income:{d['idempotency_key']}"
    with transaction.atomic():
        existing = Payment.objects.filter(idempotency_key=key, sale__isnull=False).select_related("sale").first()
        if existing:
            return existing.sale
        job = create_job(user=request.user, lines=job_lines, walk_in_customer_name=d["customer_name"], notes=d["note"], allow_price_change=True)
        return complete_job(job=job, user=request.user, payment_method=d["payment_method"],
                            payment_reference=d["payment_reference"].strip().upper(), idempotency_key=key)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def record_visit(request):
    _require(request, "cyber.view_cyberjob")
    form = VisitInput(data=request.data)
    form.is_valid(raise_exception=True)
    sale = _record(request, form.validated_data["lines"], form.validated_data)
    return Response({"sale_id": sale.pk, "receipt_number": sale.number, "total": sale.total}, status=201)


class ChargeInput(serializers.Serializer):
    """A visit charged at the checkout, where the customer pays as at the till: cash, M-Pesa, bank, or owed."""
    lines = LineInput(many=True, allow_empty=False)
    service_id = serializers.IntegerField(required=False, allow_null=True)  # on a service's own page: only its options
    customer_id = serializers.IntegerField(required=False, allow_null=True)
    customer_name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=100)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def charge_visit(request):
    from apps.commerce.checkout import checkout_data
    from .checkout import charge_visit as charge, customer_in
    _require(request, "cyber.view_cyberjob", "cyber.add_cyberjob", "cyber.complete_cyber_job")
    form = ChargeInput(data=request.data)
    form.is_valid(raise_exception=True)
    d = form.validated_data
    product = get_object_or_404(Product, pk=d["service_id"]) if d.get("service_id") else None
    checkout = charge(user=request.user, store=request.store, key=d["idempotency_key"], lines=_job_lines(request, d["lines"], product),
                      customer=customer_in(request.organization, d.get("customer_id")), customer_name=d["customer_name"])
    return Response(checkout_data(checkout, user=request.user, with_candidates=True), status=201)


def _check_amount(user, profile, quantity, amount):
    """Whether this person may take this amount for this option: managers always; anyone when the amount varies;
    otherwise from the option's lowest price up to its list price."""
    variant = profile.variant
    listed = (quantity * variant.selling_price).quantize(CENT, ROUND_HALF_UP)
    # No price set yet works like an amount that varies, until the owner sets one.
    if amount == listed or profile.price_varies or variant.selling_price <= 0 or has_business_permission(user, "cyber.change_cyberjobline"):
        return
    lowest = (quantity * variant.minimum_price).quantize(CENT, ROUND_HALF_UP)
    if variant.minimum_price > 0 and lowest <= amount < listed:
        return
    if variant.minimum_price > 0 and amount < listed:
        unit = _unit(profile.billing_unit)
        each = f" ({variant.minimum_price:,.2f} per {unit})" if unit else ""
        raise ValidationError(f"The lowest for this is {lowest:,.2f}{each}. A lower amount needs a manager.")
    if amount > listed:
        raise ValidationError(f"The price for this is {listed:,.2f}. Charging more needs a manager.")
    raise ValidationError(f"The price for this is fixed at {listed:,.2f}. A different amount needs a manager.")


def _line(profile, quantity, amount):
    """The job line for the amount received: its price each, or (when the amount does not divide evenly) one line
    for the whole amount with the real number of units kept in its details."""
    if amount is None:
        return {"variant_id": profile.variant_id, "quantity": str(quantity)}
    each = (amount / quantity).quantize(CENT, ROUND_HALF_UP)
    if (each * quantity).quantize(CENT, ROUND_HALF_UP) == amount:
        return {"variant_id": profile.variant_id, "quantity": str(quantity), "unit_price": str(each)}
    return {"variant_id": profile.variant_id, "quantity": "1", "unit_price": str(amount), "service_details": {"units": str(quantity)}}


def _detail(request, product_id, status=200):
    rows = _services(request, product_id)
    if not rows:
        raise ValidationError("This is not a Cyber service.")
    options = [o["id"] for o in rows[0]["options"]]
    lines = (_earned().filter(variant__cyber_profile__in=options).select_related("job__operator", "job__sale", "variant")
             .prefetch_related("job__sale__payments").order_by("-job__completed_at")[:150])
    history = [{"id": line.pk, "date": line.job.completed_at, "option": line.variant.name,
                "quantity": Decimal(str((line.service_details or {}).get("units", line.quantity))), "amount": line.line_total,
                "receipt_number": line.job.number, "sale_id": line.job.sale_id, "customer": line.job.walk_in_customer_name,
                "payment_method": (line.job.sale.payments.order_by("pk").first() or Payment(method="")).method,
                "recorded_by": (line.job.operator.get_full_name() or line.job.operator.username) if line.job.operator else ""}
               for line in lines]
    return Response({**rows[0], "history": history, "groups": groups()}, status=status)


@api_view(["GET", "POST"])
@permission_classes([HasLinTechPermission])
def service_income(request, pk):
    _require(request, "cyber.view_cyberjob")
    product = get_object_or_404(Product, pk=pk, product_type=Product.SERVICE)
    if request.method == "GET":
        return _detail(request, product.pk)
    form = IncomeInput(data=request.data)
    form.is_valid(raise_exception=True)
    _record(request, [form.validated_data], form.validated_data, product=product)
    return _detail(request, product.pk, status=201)


class OptionInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=ZERO)
    minimum_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=ZERO, required=False, default=ZERO)
    billing_unit = serializers.ChoiceField(choices=UNITS)
    price_varies = serializers.BooleanField(default=False)
    cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=ZERO, required=False, allow_null=True)
    active = serializers.BooleanField(default=True)


def _save_option(request, profile, d):
    variant = profile.variant
    name = " ".join(d["name"].split())[:120]
    if not name:
        raise ValidationError("Give the price option a name, e.g. Single side.")
    if ProductVariant.objects.filter(product_id=variant.product_id, name__iexact=name).exclude(pk=variant.pk).exists():
        raise ValidationError(f"This service already has a price option called {name}.")
    minimum = ZERO if d["price_varies"] else d["minimum_price"]
    check_price_range(d["price"], minimum)
    others_in_use = CyberServiceProfile.objects.filter(variant__product_id=variant.product_id, active=True, variant__active=True).exclude(pk=profile.pk)
    if not d["active"] and profile.pk and not others_in_use.exists():
        raise ValidationError("A service needs at least one price option in use. Hide the whole service on the Service Desk instead.")
    before = {"name": variant.name, "price": str(variant.selling_price), "minimum_price": str(variant.minimum_price),
              "billing_unit": profile.billing_unit, "price_varies": profile.price_varies, "active": profile.active}
    variant.name, variant.selling_price, variant.minimum_price, variant.active = name, d["price"], minimum, True
    fields = ["name", "selling_price", "minimum_price", "active", "updated_at"]
    if d.get("cost") is not None and has_business_permission(request.user, "accounting.view_profit"):
        variant.service_cost = d["cost"]
        fields.append("service_cost")
    variant.save(update_fields=fields)
    profile.billing_unit, profile.price_varies, profile.active = d["billing_unit"], d["price_varies"], d["active"]
    profile.save(update_fields=["billing_unit", "price_varies", "active", "updated_at"])
    AuditLog.objects.create(action="CYBER_PRICE_OPTION_SAVED", object_type="CyberServiceProfile", object_id=str(profile.pk), user=request.user,
                            before=before, after={"service": variant.product.name, "name": name, "price": str(d["price"]),
                                                  "minimum_price": str(minimum), "billing_unit": d["billing_unit"],
                                                  "price_varies": d["price_varies"], "active": d["active"]})


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def add_option(request, pk):
    """Another price option for a service, e.g. "Both sides" next to "Single side"."""
    _require(request, "cyber.add_cyberserviceprofile", "catalog.add_productvariant")
    product = get_object_or_404(Product, pk=pk, product_type=Product.SERVICE)
    first = CyberServiceProfile.objects.filter(variant__product=product).select_related("variant").order_by("pk").first()
    if not first:
        raise ValidationError("This is not a Cyber service.")
    form = OptionInput(data=request.data)
    form.is_valid(raise_exception=True)
    with transaction.atomic():
        profile = add_price_option(product, name=f"option {product.variants.count() + 1}", billing_unit=form.validated_data["billing_unit"], notes=first.notes)
        _save_option(request, profile, form.validated_data)
    return _detail(request, product.pk, status=201)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def edit_option(request, pk):
    _require(request, "cyber.change_cyberserviceprofile", "catalog.change_productvariant")
    profile = get_object_or_404(CyberServiceProfile.objects.select_related("variant__product"), pk=pk)
    form = OptionInput(data=request.data)
    form.is_valid(raise_exception=True)
    with transaction.atomic():
        _save_option(request, profile, form.validated_data)
    return _detail(request, profile.variant.product_id)


class GroupInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    parent_id = serializers.IntegerField(required=False, allow_null=True)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def add_group(request):
    """A new service group (e.g. "Design & Branding"), or a sub-group inside one (e.g. "NTSA & Education")."""
    _require(request, "cyber.view_cyberjob", "catalog.add_category")
    form = GroupInput(data=request.data)
    form.is_valid(raise_exception=True)
    from django.utils.text import slugify
    root = services_category()
    parent = root
    if form.validated_data.get("parent_id"):
        parent = Category.objects.filter(pk=form.validated_data["parent_id"], parent=root, active=True).first()
        if not parent:
            raise ValidationError("Sub-groups go inside one of your main service groups.")
    name = " ".join(form.validated_data["name"].split())
    if Category.objects.filter(parent=parent, name__iexact=name, active=True).exists():
        raise ValidationError(f"There is already a group called {name}.")
    base = f"services-{slugify(name)[:36] or 'group'}"
    slug, number = base, 1
    while Category.objects.filter(slug=slug).exists():
        number += 1
        slug = f"{base}-{number}"
    Category.objects.create(name=name[:120], slug=slug, parent=parent)
    return Response({"groups": groups()}, status=201)


class ServiceSettingsInput(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def service_settings(request, pk):
    """A service's name, group and note. Past income stays under the service."""
    _require(request, "cyber.change_cyberserviceprofile", "catalog.change_product")
    product = get_object_or_404(Product, pk=pk, product_type=Product.SERVICE)
    form = ServiceSettingsInput(data=request.data)
    form.is_valid(raise_exception=True)
    d = form.validated_data
    name = " ".join(d["name"].split())[:160]
    if not name:
        raise ValidationError("Give the service a name.")
    if CyberServiceProfile.objects.filter(variant__product__name__iexact=name).exclude(variant__product=product).exists():
        raise ValidationError(f"You already have a service called {name}.")
    category = _group_category(d.get("category_id"))
    before = {"name": product.name, "category": product.category_id}
    with transaction.atomic():
        product.name, product.category = name, category
        product.save(update_fields=["name", "category", "updated_at"])
        CyberServiceProfile.objects.filter(variant__product=product).update(notes=d["notes"].strip())
        AuditLog.objects.create(action="CYBER_SERVICE_SAVED", object_type="Product", object_id=str(product.pk), user=request.user,
                                before=before, after={"name": name, "category": category.pk})
    return _detail(request, product.pk)


@api_view(["POST"])
@permission_classes([HasLinTechPermission])
def delete_service(request, pk):
    """Deletes a service. One never used is erased; one with income recorded is removed from every list and can no
    longer be sold, while its past income, receipts and the books stay as they were."""
    _require(request, "cyber.delete_cyberserviceprofile")
    product = get_object_or_404(Product, pk=pk, product_type=Product.SERVICE)
    from apps.commerce.models import OrderItem, SaleItem
    from .models import ServiceMaterialRequirement
    with transaction.atomic():
        profiles = CyberServiceProfile.objects.select_for_update().filter(variant__product=product, removed_at__isnull=True)
        if not profiles.exists():
            raise ValidationError("This service is already deleted.")
        variants = product.variants.all()
        used = (CyberJobLine.objects.filter(variant__in=variants).exists() or SaleItem.objects.filter(variant__in=variants).exists()
                or OrderItem.objects.filter(variant__in=variants).exists())
        if used:
            profiles.update(active=False, removed_at=timezone.now())
            variants.update(active=False)
            Product.objects.filter(pk=product.pk).update(active=False)
            result = "removed"
        else:
            ServiceMaterialRequirement.objects.filter(service_variant__in=variants).delete()
            CyberServiceProfile.objects.filter(variant__product=product).delete()
            product.delete()
            result = "deleted"
        AuditLog.objects.create(action="CYBER_SERVICE_DELETED", object_type="Product", object_id=str(pk), user=request.user,
                                before={"name": product.name}, after={"result": result})
    return Response({"result": result, "name": product.name})
