"""What the app expects in each place money is kept, against what was actually counted.

Expected = starting money + money received − money spent − suppliers paid ± money lent and repaid ± money invested,
from the cash book. These are the owner's own places (drawer, Lipa na M-Pesa till, bank): every part of the business is
in them, each amount labelled with the part that brought it, including commission the M-Pesa agency paid out to the
owner. The agency's own cash and float are kept in their own accounts and checked on the M-Pesa desk, never here.
With separate drawers (money_mode.SEPARATE_CASH) each part's cash drawer is expected and counted on its own.
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from apps.tenancy.transactions import lock_business
from .ledger import money, resolve_branch
from .models import CashEntry, MoneyCheck
from .money_mode import business_parts, money_names, part_names, separate_cash
from .services import post

# The owner's own places. The agency's cash and float (AGENCY_CASH, AGENCY_FLOAT) are never one of them.
PLACES = [("CASH", "Cash in the drawer"), ("MPESA", "Lipa na M-Pesa till"), ("BANK", "Bank"), ("OTHER", "Other")]
PARTS = [("OPENING", "starting", "Starting money"), ("INCOME", "received", "Received from customers (less refunds)"),
         ("EXPENSE", "expenses", "Spent on running costs"), ("PURCHASE", "suppliers", "Paid to suppliers"),
         ("LOAN", "loans", "Money lent, less repayments"), ("INVESTMENT", "invested", "Put into investments, less taken out")]
ZERO = Decimal("0")


def _entries(method, unit=None):
    rows = CashEntry.objects.filter(account__payment_method=method)
    return rows.filter(business_unit=unit) if unit else rows


def expected(method, unit=None):
    rows = dict(_entries(method, unit).values_list("kind").annotate(v=Sum("amount")))
    parts = {key: rows.get(kind) or ZERO for kind, key, _ in PARTS}
    return sum(parts.values(), ZERO), parts


def by_part(method, unit=None):
    """How much of what is expected in a place each part of the business brought (what it took in less what it paid
    out from there): [{"unit", "label", "amount"}], so a shared drawer still says whose money is whose."""
    rows = dict(_entries(method, unit).values_list("business_unit").annotate(v=Sum("amount")))
    return [{"unit": key, "label": money_names().get(key, key), "amount": rows.get(key) or ZERO}
            for key in [*business_parts(), *sorted(set(rows) - set(business_parts()))] if key in rows or key in business_parts()]


def _place(method, label, unit=None):
    total, parts = expected(method, unit)
    checks = MoneyCheck.objects.filter(method=method)
    last = (checks.filter(business_unit=unit) if unit else checks).first()
    return {"key": f"{method}:{unit}" if unit else method, "method": method, "unit": unit, "label": label, "expected": total,
            "parts": [{"key": key, "label": text, "amount": parts[key]} for _, key, text in PARTS],
            "by_part": by_part(method, unit), "last_check": check_row(last) if last else None}


def _cash_units():
    """With separate drawers: one drawer for each part the business runs, and any other part that has cash."""
    used = set(CashEntry.objects.filter(account__payment_method="CASH").values_list("business_unit", flat=True).distinct())
    return [*business_parts(), *sorted(used - set(business_parts()))]


def places():
    result = []
    for method, label in PLACES:
        if method == "CASH" and separate_cash():
            for unit in _cash_units():
                name = "M-Pesa commission cash" if unit == "MPESA" else f"{part_names().get(unit, unit)} cash drawer"
                result.append(_place(method, name, unit))
            continue
        place = _place(method, label)
        if method in {"BANK", "OTHER"} and not place["expected"] and not place["last_check"] and not any(p["amount"] for p in place["parts"]):
            continue  # not used by this business
        result.append(place)
    return result


def check_row(check):
    return {"id": check.pk, "method": check.method, "unit": check.business_unit or None, "expected": check.expected, "actual": check.actual, "difference": check.difference,
            "note": check.note, "cash_count": check.cash_count, "created_at": check.created_at,
            "counted_by": (check.created_by.get_full_name() or check.created_by.username) if check.created_by else ""}


@transaction.atomic
def record_check(*, user, method, actual=None, cash_count=None, note="", unit=None):
    from apps.mpesa.services import counted_cash
    lock_business()
    if method not in dict(PLACES):
        raise ValidationError("Choose where the money is kept.")
    unit = _drawer(method, unit)
    if cash_count and method != "CASH":
        raise ValidationError("Notes and coins are counted for the cash drawer only.")
    counted, count = counted_cash(actual, cash_count)
    counted = money(counted)
    if counted < 0:
        raise ValidationError("The amount you have cannot be below zero.")
    total, _ = expected(method, unit)
    check = MoneyCheck.objects.create(branch=resolve_branch(), method=method, business_unit=unit or "", expected=total, actual=counted,
                                      difference=counted - total, cash_count=count, note=str(note or "").strip(), created_by=user)
    return check


@transaction.atomic
def add_starting_money(*, user, method, amount, note="", key, unit=None):
    """Money you already had in a place when you started using the app (or found you had not recorded). With separate
    drawers, cash goes into the drawer of the part it belongs to; otherwise it is the business's own (the shop's)."""
    lock_business()
    if method not in dict(PLACES):
        raise ValidationError("Choose where the money is kept.")
    unit = _drawer(method, unit) or (unit if unit in business_parts() else "SHOP")
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    return post(unit=unit, method=method, amount=amount, kind="OPENING", reference=(note or "Starting money")[:160],
                key=f"opening:{key}", user=user, reason=note, branch=resolve_branch())


def _drawer(method, unit):
    """The part whose drawer is meant: needed for cash when each part keeps its own drawer, otherwise none."""
    if method != "CASH" or not separate_cash():
        return None
    if unit not in _cash_units():
        raise ValidationError("Choose whose cash drawer this is.")
    return unit
