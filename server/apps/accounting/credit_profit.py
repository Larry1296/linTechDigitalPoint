"""Profit still owed by customers: the profit in sales not yet paid for.

A sale's profit counts as its money comes in. A sale paid in full straight away counts in full the same day; a sale
on credit counts the share of its profit that has been paid, and the rest when the customer pays (the instalment
method). So the profit shown is money the business really has, ready to restock or invest, never money still owed.
The books themselves keep every sale on the day it was made: sales, stock and what customers owe stay as they are.

For each sale with something owed at the end of a day, the profit still owed is its profit share (its profit, never
below zero, over what it charged) times what the customer still owes then. Payments, price corrections, returns and
refunds change what is owed, on the day they happen. A sale cancelled or refunded in full owes nothing.
"""
from collections import defaultdict
from decimal import Decimal
from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _day(moment):
    return timezone.localtime(moment).date() if timezone.is_aware(moment) else moment.date()


def _unit(sale):
    from apps.commerce.models import Sale
    return "CYBER" if sale.channel in (Sale.CYBER, Sale.ROOMS) else "SHOP"


def owed_profit_rows(start=None, end=None):
    """[{date, unit, amount}]: how the profit still owed by customers changed on each day (more owed: above zero; paid
    or returned: below zero), between ``start`` and ``end`` (either may be None). Summed up to a day, it is the profit
    still owed at the end of that day."""
    from apps.commerce.models import Sale
    # Only sales not paid in full on the day they were made can ever owe anything at a day's end.
    same_day = Coalesce(Sum("payments__amount", filter=Q(payments__status="COMPLETED", payments__updated_at__date=F("created_at__date"))),
                        Value(ZERO))
    sales = (Sale.objects.filter(status="COMPLETED", total__gt=0).annotate(same_day=same_day).filter(same_day__lt=F("total"))
             .prefetch_related("payments", "adjustments", "returns__lines"))
    rows = []
    for sale in sales:
        share = max(sale.gross_profit, ZERO) / sale.total
        if not share:
            continue
        changes = defaultdict(lambda: ZERO)
        changes[_day(sale.created_at)] += sale.total
        for payment in sale.payments.all():
            if payment.status == "COMPLETED":
                changes[_day(payment.updated_at)] -= payment.amount
        for note in sale.adjustments.all():
            changes[_day(note.created_at)] += note.amount if note.kind == "DEBIT" else -note.amount
        for sale_return in sale.returns.all():
            changes[_day(sale_return.created_at)] += sale_return.refund_amount - sum((line.payable_amount for line in sale_return.lines.all()), ZERO)
        owed, before = ZERO, ZERO
        for day in sorted(changes):
            owed += changes[day]
            now = (share * max(owed, ZERO)).quantize(CENT)
            if now != before and (start is None or day >= start) and (end is None or day <= end):
                rows.append({"date": day, "unit": _unit(sale), "amount": now - before})
            before = now
    return rows


def owed_profit(on=None):
    """The profit still owed by customers at the end of ``on`` (default: now)."""
    return sum((row["amount"] for row in owed_profit_rows(end=on)), ZERO)
