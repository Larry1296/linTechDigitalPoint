from apps.tenancy.transactions import lock_business
from apps.tenancy.permissions import has_business_permission, is_business_manager
"""Physical-count corrections; receipts and sales are never rewritten."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.catalog.models import Product, ProductVariant
from .models import Movement, Shelf, StockAdjustment, StockBalance, StockLot


# Reasons that mean stock really left the business without being sold: a loss that reduces profit.
LOSS_REASONS = {"Damaged item", "Lost item", "Physical count variance"}


def authorize(user):
    if not (user and user.is_active and has_business_permission(user, "inventory.adjust_stock")):
        raise PermissionDenied("Stock adjustment permission is required.")


def quantity(value):
    try:
        result = Decimal(str(value))
        if (
            not result.is_finite()
            or result < 0
            or result >= Decimal("100000000000")
            or result != result.quantize(Decimal(".001"))
        ):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValidationError("Quantities must be non-negative numbers with at most three decimal places.")


@transaction.atomic
def adjust_stock(
    *,
    user,
    variant_id,
    shelf_id,
    expected_quantity,
    counted_quantity,
    reason,
    idempotency_key,
    confirmed=False,
    notes="",
    reference="",
    lot_id=None,
    new_lot_unit_cost=None,
):
    lock_business()
    authorize(user)
    if confirmed is not True:
        raise ValidationError("Confirm the adjustment before posting.")
    before_expected, counted = quantity(expected_quantity), quantity(counted_quantity)
    if reason not in dict(StockAdjustment.REASONS):
        raise ValidationError("Select a valid adjustment reason.")
    if not idempotency_key or len(idempotency_key) > 120 or len(reference) > 100:
        raise ValidationError("A unique request key and a reference of at most 100 characters are required.")
    # Serialize corrections and receipts for this variant; balance locks also coordinate with POS/reservations.
    variant = (
        ProductVariant.objects.select_for_update()
        .filter(pk=variant_id, active=True, product__active=True, product__product_type=Product.STOCK_ITEM)
        .first()
    )
    if not variant:
        raise ValidationError("Select an active stock variant.")
    existing = StockAdjustment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if (
            existing.variant_id,
            existing.shelf_id,
            existing.quantity_before,
            existing.quantity_after,
            existing.reason,
            existing.notes,
            existing.reference,
            existing.performed_by_id,
        ) != (variant.pk, shelf_id, before_expected, counted, reason, notes, reference, user.pk):
            raise ValidationError("This request key already belongs to a different adjustment.")
        return existing
    shelf = (
        Shelf.objects.select_for_update(of=("self",))
        .select_related("zone", "level__stack")
        .filter(pk=shelf_id, active=True, zone__active=True)
        .first()
    )
    if not shelf or (shelf.level_id and (not shelf.level.active or not shelf.level.stack.active)):
        raise ValidationError("Select an active shelf compartment in an active rack and zone.")
    rows = list(
        StockBalance.objects.select_for_update()
        .select_related("lot")
        .filter(lot__variant=variant, shelf=shelf)
        .order_by("lot__received_at", "lot_id", "shelf_id")
    )
    before = sum((row.quantity for row in rows), Decimal(0))
    reserved = sum((row.reserved for row in rows), Decimal(0))
    if before != before_expected:
        raise ValidationError("Stock changed since this count was opened. Refresh and recount before posting.")
    if counted < reserved:
        raise ValidationError("The count cannot be below reserved stock. Resolve reservations first.")
    delta = counted - before
    if not delta:
        raise ValidationError("The physical count matches system stock; no adjustment is needed.")
    if delta > 0 and reason in LOSS_REASONS:
        raise ValidationError(f"\"{reason}\" can only take stock away. Choose \"Found stock\" or a correction to add stock.")
    if delta < 0 and reason == "Found stock":
        raise ValidationError("\"Found stock\" can only add stock. Choose why the stock is missing instead.")
    allocations = []
    if delta > 0:
        if lot_id:
            lot = StockLot.objects.select_for_update().filter(pk=lot_id, variant=variant).first()
            if not lot:
                raise ValidationError("Select a lot belonging to this exact variant.")
        else:
            if new_lot_unit_cost is None:
                raise ValidationError("Select the original lot or explicitly supply the cost of found stock.")
            cost = quantity(new_lot_unit_cost)
            if cost != cost.quantize(Decimal(".01")) or cost >= Decimal("1000000000000"):
                raise ValidationError("Unit cost must have at most two decimal places.")
            lot = StockLot.objects.create(
                variant=variant,
                reference=f"ADJ-{idempotency_key}"[:80],
                received_quantity=delta,  # the found units are this layer's whole receipt
                remaining_quantity=0,
                unit_cost=cost,
                received_at=timezone.now(),
            )
        row, _ = StockBalance.objects.get_or_create(lot=lot, shelf=shelf, defaults={"quantity": 0})
        allocations.append((row, delta))
    else:
        needed = -delta
        for row in rows:
            take = min(needed, row.quantity - row.reserved)
            if take:
                allocations.append((row, -take))
                needed -= take
        if needed:
            raise ValidationError("Insufficient unreserved stock for this correction.")
    adjustment = StockAdjustment.objects.create(
        variant=variant,
        shelf=shelf,
        quantity_before=before,
        amount=delta,
        quantity_after=counted,
        reason=reason,
        notes=notes,
        reference=reference,
        performed_by=user,
        idempotency_key=idempotency_key,
    )
    for row, amount in allocations:
        if not StockLot.objects.filter(pk=row.lot_id, remaining_quantity__gte=max(-amount, 0)).update(
            remaining_quantity=F("remaining_quantity") + amount
        ):
            raise ValidationError("Lot totals are inconsistent; no adjustment was posted.")
        old = row.quantity
        row.quantity += amount
        row.save(update_fields=["quantity", "updated_at"])
        Movement.objects.create(
            variant=variant,
            lot_id=row.lot_id,
            quantity=amount,
            source=shelf if amount < 0 else None,
            destination=shelf if amount > 0 else None,
            movement_type="STOCK_ADJUSTMENT",
            reference=reference,
            notes=notes,
            performed_by=user,
            adjustment=adjustment,
            quantity_before=old,
            quantity_after=row.quantity,
        )
    from apps.accounting.ledger import post_journal, paired
    value = sum((amount * row.lot.unit_cost for row, amount in allocations), Decimal(0))
    if value:
        # Profit comes only from selling. Stock found, and corrections of typing mistakes, only change what the
        # business owns (opening equity, 3000). Only a real loss of stock that was paid for (damaged, lost, or
        # short in a count) reduces profit, through "stock losses and corrections" (6100).
        loss = value < 0 and reason in LOSS_REASONS
        post_journal(key=f'adjustment:{adjustment.pk}', description=reason, branch=shelf.zone.store_id,
            user=user, lines=paired('1200', '6100' if loss else '3000', value))
    return adjustment
