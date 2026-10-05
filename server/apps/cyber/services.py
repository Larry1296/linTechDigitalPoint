from apps.tenancy.transactions import lock_business
from apps.tenancy.permissions import has_business_permission, is_business_manager
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.models import Product, ProductVariant
from apps.commerce.models import Payment, Sale, SaleItem
from apps.core.models import AuditLog
from apps.inventory.services import consume_stock_fifo

from .models import CyberJob, CyberJobLine, CyberServiceProfile


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def audit(action, obj, user, before=None, after=None):
    AuditLog.objects.create(
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(obj.pk),
        user=user,
        before=before or {},
        after=after or {},
    )


@transaction.atomic
def create_job(*, user, lines, customer=None, walk_in_customer_name="", phone="", notes="", due_at=None, discount=0, allow_price_change=False):
    """``allow_price_change``: the caller has already checked an amount different from the list price against the
    service's own rules (income by service); the change is still audited."""
    if not lines:
        raise ValidationError("Add at least one cyber service.")
    job = CyberJob.objects.create(
        number=f"CYB-{timezone.now():%y%m%d}-{uuid4().hex[:6].upper()}",
        customer=customer,
        walk_in_customer_name=walk_in_customer_name,
        phone=phone,
        operator=user,
        notes=notes,
        due_at=due_at,
        discount=money(discount),
        status="QUEUED",
    )
    subtotal = Decimal("0")
    for raw in lines:
        variant = ProductVariant.objects.select_related("product", "cyber_profile").get(pk=raw["variant_id"])
        if variant.product.product_type != Product.SERVICE or not variant.active:
            raise ValidationError("Cyber jobs can only contain active service variants.")
        try:
            profile = variant.cyber_profile
        except CyberServiceProfile.DoesNotExist as exc:
            raise ValidationError(f"{variant} is not configured as a Cyber service.") from exc
        if not profile.active:
            raise ValidationError(f"{variant} is not an active Cyber service.")
        quantity = Decimal(str(raw.get("quantity", 1)))
        if quantity <= 0:
            raise ValidationError("Service quantity must be positive.")
        unit_price = money(raw.get("unit_price", variant.selling_price))
        if unit_price != variant.selling_price and not allow_price_change and not has_business_permission(user, "cyber.change_cyberjobline"):
            raise ValidationError("Cyber price override permission required.")
        total = money(quantity * unit_price)
        CyberJobLine.objects.create(
            job=job,
            variant=variant,
            service_name=variant.product.name,
            quantity=quantity,
            billing_unit=profile.billing_unit,
            unit_price=unit_price,
            line_total=total,
            service_details=raw.get("service_details") or {},
        )
        subtotal += total
        if unit_price != variant.selling_price:
            audit("CYBER_PRICE_OVERRIDE", job, user, after={"variant": variant.id, "unit_price": str(unit_price)})
    if job.discount < 0 or job.discount > subtotal:
        raise ValidationError("Discount must be between zero and the subtotal.")
    job.subtotal = subtotal
    job.total = subtotal - job.discount
    job.save(update_fields=["subtotal", "total", "updated_at"])
    audit("CYBER_JOB_CREATED", job, user, after={"number": job.number, "total": str(job.total)})
    return job


@transaction.atomic
def delete_job(*, job, user):
    """A job created by mistake, removed completely while it is still waiting: nothing was started, sold or paid for it,
    so no stock, sale or books depend on it. The audit log keeps what was deleted."""
    job = CyberJob.objects.select_for_update().get(pk=job.pk)
    if job.status != "QUEUED" or job.started_at or job.sale_id:
        raise ValidationError("Only a job that has not started yet can be deleted.")
    snapshot = {"number": job.number, "customer": job.walk_in_customer_name, "total": str(job.total),
                "lines": [{"service": line.service_name, "quantity": str(line.quantity), "total": str(line.line_total)} for line in job.lines.all()]}
    audit("CYBER_JOB_DELETED", job, user, before=snapshot)
    job.lines.all().delete()
    job.delete()


@transaction.atomic
def set_job_status(*, job, status, user):
    job = CyberJob.objects.select_for_update().get(pk=job.pk)
    if job.status in ["COMPLETED", "CANCELLED"]:
        raise ValidationError("A completed or cancelled job cannot be changed.")
    allowed = {choice[0] for choice in CyberJob.STATUSES} - {"COMPLETED"}
    if status not in allowed:
        raise ValidationError("Invalid Cyber job status.")
    before = job.status
    job.status = status
    if status == "IN_PROGRESS" and not job.started_at:
        job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])
    action = "CYBER_JOB_CANCELLED" if status == "CANCELLED" else "CYBER_JOB_STARTED" if status == "IN_PROGRESS" else "CYBER_JOB_UPDATED"
    audit(action, job, user, before={"status": before}, after={"status": status})
    return job


@transaction.atomic
def complete_job(*, job, user, payment_method, payment_reference="", idempotency_key=None):
    lock_business()
    job = CyberJob.objects.select_for_update().prefetch_related(
        "lines__variant__product", "lines__variant__material_requirements__material_variant"
    ).get(pk=job.pk)
    if job.sale_id:
        return job.sale
    if job.status == "CANCELLED":
        raise ValidationError("A cancelled job cannot be completed.")
    key = idempotency_key or f"cyber:{job.number}"
    existing = Payment.objects.filter(idempotency_key=key, sale__isnull=False).select_related("sale").first()
    if existing:
        return existing.sale
    sale = Sale.objects.create(
        number=job.number,
        channel=Sale.CYBER,
        customer=job.customer,
        created_by=user,
        subtotal=job.subtotal,
        discount=job.discount,
        total=job.total,
    )
    from apps.commerce.pricing import cents, price_line, spread_discount, tax_config
    from apps.tenancy.models import Organization
    from apps.tenancy.context import organization_id
    tax = tax_config(Organization.objects.get(pk=organization_id()))
    job_lines = list(job.lines.all())
    shares = spread_discount([cents(line.quantity * line.unit_price) for line in job_lines], job.discount)
    totals = {"gross": Decimal("0"), "discount": Decimal("0"), "tax": Decimal("0"), "net": Decimal("0"), "payable": Decimal("0")}
    cogs = Decimal("0")
    for line, share in zip(job_lines, shares):
        requirements = list(line.variant.material_requirements.filter(active=True).select_related("material_variant"))
        line_cost = Decimal("0")
        if requirements:
            # Measured materials are the job's direct cost; the configured service cost is then not added.
            for requirement in requirements:
                line_cost += consume_stock_fifo(
                    variant=requirement.material_variant,
                    quantity=line.quantity * requirement.quantity_per_service_unit,
                    reference=job.number,
                    movement_type="CYBER_CONSUMPTION",
                    user=user,
                )
        else:
            line_cost = line.quantity * line.variant.service_cost
        amounts = price_line(line.quantity, line.unit_price, share, tax)
        SaleItem.objects.create(
            sale=sale,
            variant=line.variant,
            quantity=line.quantity,
            list_price=line.variant.selling_price,
            unit_price=line.unit_price,
            discount=amounts["discount"],
            discount_reason="Job discount" if share else "",
            tax_amount=amounts["tax"],
            net_amount=amounts["net"],
            cost=cents(line_cost),
        )
        cogs += cents(line_cost)
        for part in totals:
            totals[part] += amounts[part]
    sale.subtotal, sale.discount, sale.tax_total = totals["gross"], totals["discount"], totals["tax"]
    sale.net_total, sale.total = totals["net"], totals["payable"]
    sale.cogs = money(cogs)
    sale.gross_profit = sale.net_total - sale.cogs
    sale.save(update_fields=["subtotal", "discount", "tax_total", "net_total", "total", "cogs", "gross_profit", "updated_at"])
    from apps.accounting.ledger import post_sale
    post_sale(sale)
    from apps.commerce.settlements import mpesa_code
    code = mpesa_code(payment_method, payment_reference)  # M-Pesa with its SMS code is confirmed; without one it waits
    Payment.objects.create(
        sale=sale,
        method=payment_method,
        amount=sale.total,
        reference=payment_reference,
        provider_transaction_id=code,
        status="MANUAL_REVIEW" if payment_method == "MPESA" and not code else "COMPLETED",
        idempotency_key=key,
    )
    job.sale = sale
    job.status = "COMPLETED"
    job.completed_at = timezone.now()
    job.save(update_fields=["sale", "status", "completed_at", "updated_at"])
    audit("CYBER_JOB_COMPLETED", job, user, after={"sale": sale.number, "total": str(sale.total)})
    return sale


@transaction.atomic
def services_category():
    """The "Services" category; service groups (Printing & Copying, Online Applications…) are its sub-categories."""
    from apps.catalog.models import Category
    category, _ = Category.objects.get_or_create(slug="services", defaults={"name": "Services"})
    return category


def create_service(user, name, selling_price, billing_unit="FIXED", requires_job=False, default_turnaround=None, notes="", category=None):
    """Create a billable service with its own catalogue entry, ready to sell at the POS or on a job card. ``category``
    is its group (a sub-category of Services); without one it goes straight under Services."""
    from django.utils.text import slugify
    from apps.inventory.services import create_product_with_opening_stock
    category = category or services_category()
    base = slugify(name)[:40] or "service"
    slug, number = base, 1
    while Product.objects.filter(slug=slug).exists():
        number += 1
        slug = f"{base}-{number}"
    sku = f"SVC-{slug.upper()}"[:64]
    while ProductVariant.objects.filter(sku=sku).exists():
        number += 1
        sku = f"SVC-{base.upper()}-{number}"[:64]
    _, variant = create_product_with_opening_stock(
        user=user,
        product_data={"name": name, "slug": slug, "category_id": category.pk, "product_type": Product.SERVICE,
                      "ecommerce_visible": False, "online_orderable": False},
        variant_data={"name": "Standard", "sku": sku, "selling_price": selling_price},
    )
    return CyberServiceProfile.objects.create(variant=variant, billing_unit=billing_unit, requires_job=requires_job,
                                              default_turnaround=default_turnaround, notes=notes)


def add_price_option(product, *, name, price=0, billing_unit="FIXED", notes=""):
    """Another price option (variant with its own Cyber profile) for a service, e.g. "Both sides" next to "Single side"."""
    first = product.variants.order_by("pk").first()
    base, number = ((first.sku if first else "") or f"SVC-{product.pk}")[:56], product.variants.count() + 1
    sku = f"{base}-{number}"
    while ProductVariant.objects.filter(sku=sku).exists():
        number += 1
        sku = f"{base}-{number}"
    variant = ProductVariant.objects.create(product=product, name=name[:120], sku=sku, selling_price=price)
    return CyberServiceProfile.objects.create(variant=variant, billing_unit=billing_unit, notes=notes)
