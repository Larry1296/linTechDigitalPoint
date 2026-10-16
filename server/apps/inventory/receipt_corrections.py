from apps.tenancy.transactions import lock_business
from apps.tenancy.permissions import has_business_permission, is_business_manager
"""Append-only corrections; physical changes are limited to unused receipt lots."""
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.catalog.models import ProductVariant, category_lineage
from apps.commerce.models import SaleAllocation
from .models import (
    Movement, ShelfStackCategory, StockBalance, StockLot, StockReceiptLine,
    StockReceiptLineCorrection,
)


class PlacementCorrectionInput(serializers.Serializer):
    shelf_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class ReceiptCorrectionInput(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))
    received_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    reason = serializers.CharField(max_length=2000, allow_blank=False)
    confirmed = serializers.BooleanField()
    expected_updated_at = serializers.DateTimeField()
    placements = PlacementCorrectionInput(many=True, required=False)


def line_snapshot(line):
    return {
        "variant_id": line.variant_id,
        "product_name": line.variant.product.name,
        "variant_name": line.variant.name,
        "sku": line.variant.sku,
        "quantity": str(line.received_quantity),
        "unit_cost": str(line.unit_cost),
        "line_total": str(line.received_quantity * line.unit_cost),
        "lot_id": line.lot_id,
        "placements": [
            {"shelf_id": p.shelf_id, "quantity": str(p.quantity)}
            for p in line.placements.order_by("shelf_id")
        ],
    }


@transaction.atomic
def correct_receipt_line(*, receipt_id, line_id, user, data):
    lock_business()
    if not (user and user.is_active and has_business_permission(user, "inventory.change_stockreceipt")):
        raise PermissionDenied("Receipt correction permission required.")
    serializer = ReceiptCorrectionInput(data=data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    if not values["confirmed"]:
        raise ValidationError("Confirm the old and new values before correcting this line.")
    line = StockReceiptLine.objects.select_for_update().filter(pk=line_id, receipt_id=receipt_id).first()
    if not line:
        raise NotFound("Receipt line not found.")
    if line.updated_at != values["expected_updated_at"]:
        raise ValidationError("This line has changed. Reload the receipt and review the latest values.")
    if not line.lot_id:
        raise ValidationError("This line has no linked stock lot; reconciliation is required.")
    # Match the balance/lot locks used by FIFO sales, reservations and transfers.
    balances = list(StockBalance.objects.select_for_update().select_related("lot")
                    .filter(lot_id=line.lot_id).order_by("lot__received_at", "lot_id", "shelf_id"))
    lot = StockLot.objects.select_for_update().get(pk=line.lot_id)
    # The lot's cost is the invoice BP plus its share of delivery costs; only the BP is corrected here.
    if (lot.variant_id, lot.received_quantity, lot.unit_cost - lot.landed_unit_cost) != (line.variant_id, line.received_quantity, line.unit_cost):
        raise ValidationError("Receipt and lot values differ; reconciliation is required before correction.")
    old_stock_value = lot.remaining_quantity * lot.unit_cost
    old_receipt_value = line.received_quantity * line.unit_cost
    before = line_snapshot(line)
    variant_changed = values["variant_id"] != line.variant_id
    quantity_changed = values["received_quantity"] != line.received_quantity
    cost_changed = values["unit_cost"] != line.unit_cost
    if cost_changed:
        from apps.tenancy.context import branch_context
        with branch_context(None):
            if StockBalance.objects.filter(lot=lot, quantity__gt=0).exclude(shelf__zone__store_id=line.receipt.branch_id).exists():
                raise ValidationError("This lot has stock in another branch. Reverse the transfer before correcting its buying price.")
    if "placements" in values and not quantity_changed:
        raise ValidationError("Only submit placement quantities when correcting received quantity.")
    if not (variant_changed or quantity_changed or cost_changed):
        raise ValidationError("No values have changed.")
    variant = line.variant
    if variant_changed:
        variant = ProductVariant.objects.select_related("product").filter(
            pk=values["variant_id"], active=True, product__active=True, product__product_type="STOCK_ITEM",
        ).first()
        if not variant:
            raise ValidationError("Choose an active stock-item variant.")
    placements = list(line.placements.select_for_update(of=("self",)).select_related("shelf__level").order_by("shelf_id"))
    new_quantities = {p.shelf_id: p.quantity for p in placements}
    if variant_changed or quantity_changed:
        used = Movement.objects.filter(lot=lot, receipt_correction__isnull=True).exclude(movement_type="PURCHASE_RECEIPT").exists()
        if (used or SaleAllocation.objects.filter(lot=lot).exists() or any(b.reserved for b in balances)
                or lot.remaining_quantity != line.received_quantity
                or sum((b.quantity for b in balances), Decimal("0")) != line.received_quantity):
            raise ValidationError("This lot has been sold, allocated or otherwise used. A reversal workflow is required to correct its variant or quantity.")
        by_shelf = {b.shelf_id: b for b in balances}
        if (set(by_shelf) != set(new_quantities)
                or any(p.balance_id != by_shelf[p.shelf_id].pk or p.quantity != by_shelf[p.shelf_id].quantity for p in placements)):
            raise ValidationError("Stock placements have changed; a reversal workflow is required.")
        if quantity_changed:
            if "placements" in values:
                new_quantities = {p["shelf_id"]: p["quantity"] for p in values["placements"]}
                if len(new_quantities) != len(values["placements"]) or set(new_quantities) != set(by_shelf):
                    raise ValidationError("Provide each original compartment exactly once.")
            elif len(placements) == 1:
                new_quantities = {placements[0].shelf_id: values["received_quantity"]}
            else:
                raise ValidationError("Provide corrected quantities for each original compartment.")
            if sum(new_quantities.values(), Decimal("0")) != values["received_quantity"]:
                raise ValidationError("Compartment quantities must equal the corrected received quantity.")
        if variant_changed:
            for p in placements:
                if not p.shelf.level_id or not ShelfStackCategory.objects.filter(
                    stack_id=p.shelf.level.stack_id, category_id__in=category_lineage(variant.product.category_id),
                ).exists():
                    raise ValidationError("The selected variant's category is not assigned to this receipt's rack. Transfer or reverse the stock first.")

    line.variant = variant
    line.received_quantity = values["received_quantity"]
    line.unit_cost = values["unit_cost"]
    line_fields = ["updated_at"]
    if variant_changed:
        line_fields.append("variant")
    if quantity_changed:
        line_fields.append("received_quantity")
    if cost_changed:
        line_fields.append("unit_cost")
    line.save(update_fields=line_fields)
    lot_fields = ["updated_at"]
    if cost_changed:
        lot.unit_cost = line.unit_cost + lot.landed_unit_cost
        lot_fields.append("unit_cost")
    if variant_changed:
        lot.variant = variant
        lot_fields.append("variant")
    if quantity_changed:
        lot.received_quantity = line.received_quantity
        lot.remaining_quantity = line.received_quantity
        lot_fields.extend(["received_quantity", "remaining_quantity"])
    lot.save(update_fields=lot_fields)
    if quantity_changed:
        for p in placements:
            p.quantity = new_quantities[p.shelf_id]
            p.save(update_fields=["quantity", "updated_at"])
            balance = by_shelf[p.shelf_id]
            balance.quantity = p.quantity
            balance.save(update_fields=["quantity", "updated_at"])
    correction = StockReceiptLineCorrection.objects.create(
        line=line, performed_by=user, reason=values["reason"], before=before, after=line_snapshot(line),
    )
    # Preserve original receipt movements. Append compensating movement entries.
    if variant_changed or quantity_changed:
        for p in placements:
            old_quantity = Decimal(next(x["quantity"] for x in before["placements"] if x["shelf_id"] == p.shelf_id))
            new_quantity = new_quantities[p.shelf_id]
            entries = [(before["variant_id"], -old_quantity), (variant.pk, new_quantity)] if variant_changed else [(variant.pk, new_quantity - old_quantity)]
            for variant_id, delta in entries:
                if not delta:
                    continue
                Movement.objects.create(
                    variant_id=variant_id, lot=lot, quantity=abs(delta),
                    source=p.shelf if delta < 0 else None, destination=p.shelf if delta > 0 else None,
                    movement_type="MANUAL_ADJUSTMENT", reference=f"RECEIPT-CORRECTION-{correction.pk}",
                    performed_by=user, notes=values["reason"], receipt_correction=correction,
                )
    from apps.accounting.ledger import post_journal, paired, money
    from apps.accounting.models import JournalEntry, SupplierPurchase
    purchase = SupplierPurchase.objects.filter(receipt=line.receipt).first()
    if purchase and JournalEntry.objects.filter(source_key=f'purchase:{purchase.pk}').exists():
        # A receipt marked as stock already owned has its value in opening equity, not owed to the supplier.
        other = '3000' if line.receipt.document_status == line.receipt.OPENING_BALANCE else '2000'
        stock_change = money(lot.remaining_quantity * lot.unit_cost - old_stock_value)
        purchase_change = money(line.received_quantity * line.unit_cost - old_receipt_value)
        if purchase_change:
            # What is owed to the supplier follows the corrected invoice.
            SupplierPurchase.objects.filter(pk=purchase.pk).update(amount=F("amount") + purchase_change)
        if stock_change or purchase_change:
            post_journal(key=f'receipt-correction:{correction.pk}', description=values['reason'],
                branch=line.receipt.branch_id, user=user,
                lines=paired('1200',other,stock_change)+paired('6100',other,purchase_change-stock_change))
    return line
