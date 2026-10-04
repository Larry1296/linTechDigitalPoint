"""Returning goods to a supplier, and supplying the missing cost of an uncosted opening balance."""
from decimal import Decimal
from uuid import uuid4
from django.db import transaction
from django.db.models import F, Sum
from rest_framework.exceptions import ValidationError
from apps.core.models import AuditLog
from apps.tenancy.transactions import lock_business
from .models import LotCostCorrection, Movement, PurchaseReturn, PurchaseReturnLine, StockBalance, StockLot, StockReceipt

CENT = Decimal("0.01")


@transaction.atomic
def return_to_supplier(*, receipt, lines, reason, user, idempotency_key=None):
    """Sends received goods back: reduces the original cost layer and what is owed, at that layer's cost.

    ``lines`` is a list of {"line_id": receipt line, "quantity": units}. Stock already sold cannot be returned.
    """
    from apps.accounting.ledger import paired, post_journal
    lock_business()
    if idempotency_key:
        existing = PurchaseReturn.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    if not reason or not reason.strip():
        raise ValidationError("Explain why the goods are going back to the supplier.")
    receipt = StockReceipt.objects.select_for_update().get(pk=receipt.pk)
    if not lines:
        raise ValidationError("Choose at least one line to return.")
    purchase_return = PurchaseReturn.objects.create(receipt=receipt, branch=receipt.branch, number=f"PRN-{uuid4().hex[:10].upper()}",
                                                    reason=reason.strip(), created_by=user, idempotency_key=idempotency_key)
    total = Decimal("0")
    for index, raw in enumerate(lines):
        line = receipt.lines.select_related("lot", "variant").filter(pk=raw.get("line_id")).first()
        quantity = Decimal(str(raw.get("quantity") or 0))
        if not line or not line.lot_id:
            raise ValidationError({f"lines[{index}]": "Choose a line from this receipt."})
        lot = StockLot.objects.select_for_update().get(pk=line.lot_id)
        if quantity <= 0 or quantity > lot.remaining_quantity:
            raise ValidationError({f"lines[{index}].quantity": f"Only {lot.remaining_quantity} unit(s) of this delivery are still in stock."})
        need = quantity
        for balance in StockBalance.objects.select_for_update().filter(lot=lot, quantity__gt=F("reserved")).select_related("shelf").order_by("shelf_id"):
            take = min(need, balance.quantity - balance.reserved)
            balance.quantity -= take
            balance.save(update_fields=["quantity", "updated_at"])
            PurchaseReturnLine.objects.create(purchase_return=purchase_return, lot=lot, shelf=balance.shelf, quantity=take, unit_cost=lot.unit_cost)
            Movement.objects.create(variant=line.variant, lot=lot, quantity=take, source=balance.shelf, movement_type="PURCHASE_RETURN",
                                    reference=purchase_return.number, performed_by=user)
            need -= take
            if not need:
                break
        if need:
            raise ValidationError({f"lines[{index}].quantity": "Some of these units are reserved for customers and cannot be returned now."})
        StockLot.objects.filter(pk=lot.pk).update(remaining_quantity=F("remaining_quantity") - quantity)
        total += quantity * lot.unit_cost
    purchase_return.total_cost = total.quantize(CENT)
    purchase_return.save(update_fields=["total_cost", "updated_at"])
    if purchase_return.total_cost:
        post_journal(key=f"purchase-return:{purchase_return.pk}", description=f"Returned to supplier {purchase_return.number}",
                     branch=receipt.branch_id, user=user, lines=paired("2000", "1200", purchase_return.total_cost))
    AuditLog.objects.create(action="PURCHASE_RETURNED", object_type="StockReceipt", object_id=str(receipt.pk), user=user,
                            after={"number": purchase_return.number, "value": str(purchase_return.total_cost), "reason": reason.strip()})
    return purchase_return


@transaction.atomic
def correct_lot_cost(*, lot, unit_cost, reason, user):
    """Sets the buying price (BP) of a cost layer: supplies a missing one, or corrects one entered by mistake.

    A supplier delivery is corrected through its receipt line, so what is owed to the supplier changes with it.
    Opening stock is revalued against opening equity (it existed before the books started): stock still held
    is valued at the new cost and units already sold or used get the difference in cost of goods sold now.
    Historical sale lines are not edited; this correction and its journal explain the change.
    """
    from apps.accounting.ledger import money, paired, post_journal, resolve_branch
    from apps.accounting.models import JournalEntry
    lock_business()
    lot = StockLot.objects.select_for_update().get(pk=lot.pk)
    try:
        unit_cost = Decimal(str(unit_cost))
    except ArithmeticError:
        unit_cost = Decimal("NaN")
    if not unit_cost.is_finite() or unit_cost <= 0:
        raise ValidationError("Enter the buying price for one unit.")
    if not reason or not reason.strip():
        raise ValidationError("Explain where the buying price comes from.")
    uncosted = lot.cost_status == StockLot.UNCOSTED
    receipt_line = getattr(lot, "receipt_line", None)
    if not uncosted and receipt_line and receipt_line.receipt.document_status != StockReceipt.OPENING_BALANCE:
        from .receipt_corrections import correct_receipt_line
        correct_receipt_line(receipt_id=receipt_line.receipt_id, line_id=receipt_line.pk, user=user, data={
            "variant_id": receipt_line.variant_id, "unit_cost": unit_cost, "received_quantity": receipt_line.received_quantity,
            "reason": reason, "confirmed": True, "expected_updated_at": receipt_line.updated_at})
        return None
    old_cost = Decimal("0") if uncosted else lot.unit_cost
    new_cost = unit_cost + lot.landed_unit_cost
    if new_cost == old_cost:
        raise ValidationError("That is already the buying price.")
    returned = lot.purchase_returns.aggregate(q=Sum("quantity"))["q"] or Decimal("0")
    consumed = lot.received_quantity - lot.remaining_quantity - returned
    inventory, cogs = money(lot.remaining_quantity * (new_cost - old_cost)), money(consumed * (new_cost - old_cost))
    correction = LotCostCorrection.objects.create(lot=lot, unit_cost=unit_cost, remaining_quantity=lot.remaining_quantity, sold_quantity=consumed,
                                                  inventory_amount=inventory, cogs_amount=cogs, reason=reason.strip(), created_by=user)
    StockLot.objects.filter(pk=lot.pk).update(unit_cost=new_cost, cost_status=StockLot.COSTED)
    if receipt_line and not receipt_line.uncosted:
        type(receipt_line).objects.filter(pk=receipt_line.pk).update(unit_cost=unit_cost)
    branch = receipt_line.receipt.branch_id if receipt_line and receipt_line.receipt.branch_id else resolve_branch().pk
    # Stock received through the older direct path was booked against the supplier, not opening equity.
    other = "2000" if JournalEntry.objects.filter(source_key=f"lot:{lot.pk}").exists() else "3000"
    if inventory or cogs:
        post_journal(key=f"lot-cost:{correction.pk}", description=f"Buying price {'supplied' if uncosted else 'corrected'} for {lot.reference}: {reason.strip()}"[:240],
                     branch=branch, user=user, lines=paired("1200", other, inventory) + paired("5000", other, cogs))
    AuditLog.objects.create(action="LOT_COST_SUPPLIED" if uncosted else "LOT_COST_CORRECTED", object_type="StockLot", object_id=str(lot.pk), user=user,
                            before={"unit_cost": None if uncosted else str(old_cost)},
                            after={"unit_cost": str(new_cost), "inventory": str(inventory), "cogs": str(cogs), "reason": reason.strip()})
    return correction
