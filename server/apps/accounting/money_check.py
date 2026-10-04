"""What the app expects in each place money is kept, against what was actually counted.

Expected = starting money + money received − money spent − suppliers paid ± money lent and repaid ± money invested,
from the cash book. Only the shop's own money is here: everything recorded under the M-Pesa agency (its cash, float and any
commission) is separate and is checked on the M-Pesa desk.
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from apps.tenancy.transactions import lock_business
from .ledger import money, resolve_branch
from .models import CashEntry, MoneyCheck
from .services import post

# The shop's own money: its drawer and its Lipa na M-Pesa till. The M-Pesa agency line is never here.
PLACES = [("CASH", "Cash in the drawer"), ("MPESA", "Lipa na M-Pesa till"), ("BANK", "Bank"), ("OTHER", "Other")]
SHOP_UNITS = ["SHOP", "CYBER"]  # never the M-Pesa agency
PARTS = [("OPENING", "starting", "Starting money"), ("INCOME", "received", "Received from customers (less refunds)"),
         ("EXPENSE", "expenses", "Spent on running costs"), ("PURCHASE", "suppliers", "Paid to suppliers"),
         ("LOAN", "loans", "Money lent, less repayments"), ("INVESTMENT", "invested", "Put into investments, less taken out")]
ZERO = Decimal("0")


def expected(method):
    rows = dict(CashEntry.objects.filter(account__payment_method=method, business_unit__in=SHOP_UNITS)
                .values_list("kind").annotate(v=Sum("amount")))
    parts = {key: rows.get(kind) or ZERO for kind, key, _ in PARTS}
    return sum(parts.values(), ZERO), parts


def places():
    result = []
    for method, label in PLACES:
        total, parts = expected(method)
        last = MoneyCheck.objects.filter(method=method).first()
        if method in {"BANK", "OTHER"} and not total and not last and not any(parts.values()):
            continue  # not used by this business
        result.append({"method": method, "label": label, "expected": total,
                       "parts": [{"key": key, "label": text, "amount": parts[key]} for _, key, text in PARTS],
                       "last_check": check_row(last) if last else None})
    return result


def check_row(check):
    return {"id": check.pk, "method": check.method, "expected": check.expected, "actual": check.actual, "difference": check.difference,
            "note": check.note, "cash_count": check.cash_count, "created_at": check.created_at,
            "counted_by": (check.created_by.get_full_name() or check.created_by.username) if check.created_by else ""}


@transaction.atomic
def record_check(*, user, method, actual=None, cash_count=None, note=""):
    from apps.mpesa.services import counted_cash
    lock_business()
    if method not in dict(PLACES):
        raise ValidationError("Choose where the money is kept.")
    if cash_count and method != "CASH":
        raise ValidationError("Notes and coins are counted for the cash drawer only.")
    counted, count = counted_cash(actual, cash_count)
    counted = money(counted)
    if counted < 0:
        raise ValidationError("The amount you have cannot be below zero.")
    total, _ = expected(method)
    check = MoneyCheck.objects.create(branch=resolve_branch(), method=method, expected=total, actual=counted,
                                      difference=counted - total, cash_count=count, note=str(note or "").strip(), created_by=user)
    return check


@transaction.atomic
def add_starting_money(*, user, method, amount, note="", key):
    """Money you already had in a place when you started using the app (or found you had not recorded)."""
    lock_business()
    if method not in dict(PLACES):
        raise ValidationError("Choose where the money is kept.")
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    return post(unit="SHOP", method=method, amount=amount, kind="OPENING", reference=(note or "Starting money")[:160],
                key=f"opening:{key}", user=user, reason=note, branch=resolve_branch())
