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
def create_job(*, user, lines, customer=None, walk_in_customer_name="", phone="", notes="", due_at=None, discount=0):
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
        if unit_price != variant.selling_price and not user.has_perm("cyber.change_cyberjobline"):
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
    cogs = Decimal("0")
    for line in job.lines.all():
        requirements = list(line.variant.material_requirements.filter(active=True).select_related("material_variant"))
        line_cost = Decimal("0")
        if requirements:
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
        SaleItem.objects.create(
            sale=sale,
            variant=line.variant,
            quantity=line.quantity,
            unit_price=line.unit_price,
            cost=line_cost,
        )
        cogs += line_cost
    sale.cogs = money(cogs)
    sale.gross_profit = sale.total - sale.cogs
    sale.save(update_fields=["cogs", "gross_profit", "updated_at"])
    Payment.objects.create(
        sale=sale,
        method=payment_method,
        amount=sale.total,
        reference=payment_reference,
        status="COMPLETED",
        idempotency_key=key,
    )
    job.sale = sale
    job.status = "COMPLETED"
    job.completed_at = timezone.now()
    job.save(update_fields=["sale", "status", "completed_at", "updated_at"])
    audit("CYBER_JOB_COMPLETED", job, user, after={"sale": sale.number, "total": str(sale.total)})
    return sale
