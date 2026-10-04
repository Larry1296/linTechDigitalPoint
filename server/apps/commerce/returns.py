"""After-sale changes: partial returns, refunds and price corrections. Posted sales are never edited.

Customer balance (receivable) for a sale:
    total + debit notes − credit notes − returned amounts − completed payments + refunds
"""
from decimal import Decimal
from uuid import uuid4
from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from apps.core.models import AuditLog
from apps.tenancy.transactions import lock_business
from .models import Sale, SaleAdjustment, SaleItem, SaleReturn, SaleReturnLine
from .pricing import cents

ZERO = Decimal("0")


def sale_balance(sale):
    """What the customer still owes for a sale (negative: the business owes the customer a refund)."""
    notes = {row["kind"]: row["v"] for row in SaleAdjustment.objects.filter(sale=sale).values("kind").annotate(v=Sum("amount"))}
    returned = SaleReturnLine.objects.filter(sale_return__sale=sale).aggregate(v=Sum("payable_amount"))["v"] or ZERO
    refunded = SaleReturn.objects.filter(sale=sale).aggregate(v=Sum("refund_amount"))["v"] or ZERO
    paid = sale.payments.filter(status="COMPLETED").aggregate(v=Sum("amount"))["v"] or ZERO
    if sale.status == "REFUNDED":
        return ZERO
    return sale.total + notes.get("DEBIT", ZERO) - notes.get("CREDIT", ZERO) - returned - paid + refunded


def sale_amounts(sale):
    """(charged, collected) for a sale after returns and price corrections; their difference is sale_balance()."""
    notes = {row["kind"]: row["v"] for row in SaleAdjustment.objects.filter(sale=sale).values("kind").annotate(v=Sum("amount"))}
    returned = SaleReturnLine.objects.filter(sale_return__sale=sale).aggregate(v=Sum("payable_amount"))["v"] or ZERO
    refunded = SaleReturn.objects.filter(sale=sale).aggregate(v=Sum("refund_amount"))["v"] or ZERO
    paid = sale.payments.filter(status="COMPLETED").aggregate(v=Sum("amount"))["v"] or ZERO
    return sale.total + notes.get("DEBIT", ZERO) - notes.get("CREDIT", ZERO) - returned, paid - refunded


def item_sales(sale):
    """{item_id: (quantity kept, amount)}: each line after its returns, with price corrections shared by value."""
    return {item.pk: (item.quantity - item.returned_quantity, cents(_item_remaining(item, sale)[0]))
            for item in sale.items.all()}


def _note_share(note, item, items):
    if note.line_amounts:
        amounts = note.line_amounts.get(str(item.pk), {})
        return Decimal(amounts.get("net", "0")), Decimal(amounts.get("tax", "0"))
    # Preserve the allocation of notes posted before explicit line amounts were stored.
    base = sum((i.net_amount + i.tax_amount for i in items), ZERO)
    weight = (Decimal(item.pk == note.item_id) if note.item_id else
              (item.net_amount + item.tax_amount) / base if base else ZERO)
    return note.net_amount * weight, note.tax_amount * weight


def _item_remaining(item, sale):
    """(net, tax) still charged for a line: its price, plus/minus the price corrections that reached it, less what
    earlier returns already credited. A return credits back from this, so it can never undo more than was charged."""
    items = list(sale.items.all())
    net, tax = item.net_amount, item.tax_amount
    for note in SaleAdjustment.objects.filter(sale=sale):
        note_net, note_tax = _note_share(note, item, items)
        sign = -1 if note.kind == SaleAdjustment.CREDIT else 1
        net += sign * note_net
        tax += sign * note_tax
    prior = item.return_lines.aggregate(net=Sum("net_amount"), tax=Sum("tax_amount"))
    return max(net - (prior["net"] or ZERO), ZERO), max(tax - (prior["tax"] or ZERO), ZERO)


def _revenue_account(item):
    from apps.accounting.ledger import REVENUE_ACCOUNT
    return REVENUE_ACCOUNT[item.variant.product.product_type]


@transaction.atomic
def return_items(*, sale, lines, reason, user, refund=None, idempotency_key=None):
    """Takes back part of a sale.

    ``lines``: [{"item_id", "quantity", "restock": bool}]. Restocked units go back into the cost layers they
    came from (latest first); units not restocked (damaged) move their cost from COGS to stock losses.
    ``refund``: optional {"method", "amount"} paid back to the customer now.
    """
    from apps.accounting.ledger import cash_code, money, paired, post_journal
    from apps.accounting.services import post
    from apps.inventory.models import Movement, StockBalance, StockLot
    from django.db.models import F
    lock_business()
    if idempotency_key:
        existing = SaleReturn.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != "COMPLETED":
        raise ValidationError("Only completed sales can take returns.")
    if not reason or not reason.strip():
        raise ValidationError("Explain why the goods are being returned.")
    if not lines:
        raise ValidationError("Choose at least one line to return.")
    sale_return = SaleReturn.objects.create(sale=sale, branch=sale.branch, number=f"RTN-{uuid4().hex[:10].upper()}", reason=reason.strip(),
                                            created_by=user, idempotency_key=idempotency_key)
    journal = []
    for index, raw in enumerate(lines):
        item = SaleItem.objects.select_for_update().select_related("variant__product").filter(pk=raw.get("item_id"), sale=sale).first()
        quantity = Decimal(str(raw.get("quantity") or 0))
        if not item:
            raise ValidationError({f"lines[{index}]": "Choose a line from this sale."})
        left = item.quantity - item.returned_quantity
        if quantity <= 0 or quantity > left:
            raise ValidationError({f"lines[{index}].quantity": f"Only {left} unit(s) of this line can still be returned."})
        restock = bool(raw.get("restock", True)) and item.variant.product.product_type == "STOCK_ITEM"
        # Credited at what is still charged for the line (after credit/debit notes), shared over the units left.
        remaining_net, remaining_tax = _item_remaining(item, sale)
        if quantity == left:  # the last units take any rounding remainder, so totals return exactly
            net, tax = cents(remaining_net), cents(remaining_tax)
        else:
            net, tax = cents(remaining_net * quantity / left), cents(remaining_tax * quantity / left)
        # Cost of the returned units: from this line's allocations, latest layer first, skipping units already returned.
        cost, skip, need = ZERO, item.returned_quantity, quantity
        for allocation in item.allocations.select_related("lot", "shelf").order_by("-lot__received_at", "-lot_id", "-pk"):
            available = allocation.quantity - min(skip, allocation.quantity)
            skip = max(ZERO, skip - allocation.quantity)
            take = min(need, available)
            if take <= 0:
                continue
            cost += take * return_unit_cost(allocation)
            if restock:
                balance, _ = StockBalance.objects.select_for_update().get_or_create(lot=allocation.lot, shelf=allocation.shelf, defaults={"quantity": 0})
                balance.quantity += take
                balance.save(update_fields=["quantity", "updated_at"])
                StockLot.objects.filter(pk=allocation.lot_id).update(remaining_quantity=F("remaining_quantity") + take)
                Movement.objects.create(variant=item.variant, lot=allocation.lot, destination=allocation.shelf, quantity=take,
                                        movement_type="SALE_RETURN", reference=sale_return.number, performed_by=user)
            need -= take
            if not need:
                break
        cost = money(cost)
        SaleReturnLine.objects.create(sale_return=sale_return, item=item, quantity=quantity, restock=restock, net_amount=net,
                                      tax_amount=tax, payable_amount=net + tax, cost_amount=cost)
        SaleItem.objects.filter(pk=item.pk).update(returned_quantity=item.returned_quantity + quantity)
        journal += [(_revenue_account(item), net, 0)] + ([("2200", tax, 0)] if tax else []) + [("1100", 0, net + tax)]
        if cost:
            cost_account = "5000" if item.variant.product.product_type == "STOCK_ITEM" else "5010"
            journal += paired("1200" if restock else "6100", cost_account, cost)
    post_journal(key=f"sale-return:{sale_return.pk}", description=f"Return {sale_return.number} for {sale.number}", lines=journal,
                 branch=sale.branch_id, user=user)
    if refund and Decimal(str(refund.get("amount") or 0)) > 0:
        amount = cents(Decimal(str(refund["amount"])))
        method = str(refund.get("method") or "CASH").upper()
        if amount > -sale_balance(sale):
            raise ValidationError("A refund cannot exceed what the customer has paid beyond what they now owe.")
        SaleReturn.objects.filter(pk=sale_return.pk).update(refund_amount=amount, refund_method=method)
        post_journal(key=f"refund:{sale_return.pk}", description=f"Refund for {sale_return.number}", branch=sale.branch_id, user=user,
                     lines=paired("1100", cash_code(method), amount))
        post(unit="CYBER" if sale.channel == "CYBER" else "SHOP", method=method, amount=-amount, kind="INCOME",
             reference=f"Refund {sale_return.number}", key=f"refund:{sale_return.pk}", user=user, branch=sale.branch, journal=False)
    AuditLog.objects.create(action="SALE_ITEMS_RETURNED", object_type="Sale", object_id=str(sale.pk), user=user,
                            after={"return": sale_return.number, "reason": reason.strip()})
    sale_return.refresh_from_db()
    return sale_return


@transaction.atomic
def adjust_sale_price(*, sale, kind, amount, reason, user, item=None, idempotency_key=None):
    """A credit note (customer owes less) or debit note (owes more) correcting a posted sale's price."""
    from apps.accounting.ledger import post_journal
    lock_business()
    if idempotency_key:
        existing = SaleAdjustment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    amount = cents(Decimal(str(amount)))
    if kind not in {SaleAdjustment.CREDIT, SaleAdjustment.DEBIT}:
        raise ValidationError("Choose a credit note or a debit note.")
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    if not reason or not reason.strip():
        raise ValidationError("Explain the price correction.")
    if sale.status != "COMPLETED":
        raise ValidationError("Only completed sales can be corrected.")
    items = list(sale.items.select_related("variant__product").order_by("pk"))
    if item:
        items = [i for i in items if i.pk == item.pk]
        if not items:
            raise ValidationError("Choose a line from this sale.")
    items = [i for i in items if i.quantity > i.returned_quantity]
    if not items:
        raise ValidationError("Only items still kept by the customer can have their price corrected.")
    amounts = {i.pk: _item_remaining(i, sale) for i in items}
    base = sum((net + tax for net, tax in amounts.values()), ZERO)
    charged = sale_amounts(sale)[0]
    if kind == SaleAdjustment.CREDIT and amount > min(base, charged):
        raise ValidationError(f"A credit note cannot exceed what is still charged ({min(base, charged)}).")
    # Freeze the allocation at posting time: later returns must not redistribute a note.
    weights = {i.pk: sum(amounts[i.pk], ZERO) for i in items}
    if not base:
        weights = {i.pk: i.quantity - i.returned_quantity for i in items}
        base = sum(weights.values(), ZERO)
    remaining, weight_left, tax, line_amounts, lines = amount, base, ZERO, {}, []
    for i in items:
        weight = weights[i.pk]
        share = cents(remaining * weight / weight_left) if weight_left else ZERO
        remaining -= share
        weight_left -= weight
        net_left, tax_left = amounts[i.pk]
        taxable_base = net_left + tax_left
        tax_ratio = tax_left / taxable_base if taxable_base else (i.tax_amount / (i.net_amount + i.tax_amount) if i.net_amount + i.tax_amount else ZERO)
        line_tax = cents(share * tax_ratio)
        line_net = share - line_tax
        tax += line_tax
        line_amounts[str(i.pk)] = {"net": str(line_net), "tax": str(line_tax)}
        if line_net:
            lines.append((_revenue_account(i), line_net, 0))
    note = SaleAdjustment.objects.create(sale=sale, branch=sale.branch, item=item, kind=kind, amount=amount, net_amount=amount - tax,
                                         tax_amount=tax, line_amounts=line_amounts, reason=reason.strip(), created_by=user, idempotency_key=idempotency_key)
    if tax:
        lines.append(("2200", tax, 0))
    lines.append(("1100", 0, amount))
    if kind == SaleAdjustment.DEBIT:
        lines = [(code, credit, debit) for code, debit, credit in lines]
    post_journal(key=f"sale-note:{note.pk}", description=f"{note.get_kind_display()} for {sale.number}: {reason.strip()}"[:240],
                 lines=lines, branch=sale.branch_id, user=user)
    AuditLog.objects.create(action=f"SALE_{kind}_NOTE", object_type="Sale", object_id=str(sale.pk), user=user,
                            after={"amount": str(amount), "reason": reason.strip()})
    return note


def return_unit_cost(allocation):
    """Include a buying price supplied after an uncosted sale, without repricing costed sales."""
    if not allocation.unit_cost:
        correction = allocation.lot.cost_corrections.order_by("created_at", "pk").first()
        if correction and correction.created_at > allocation.item.sale.created_at:
            return correction.unit_cost
    return allocation.unit_cost
