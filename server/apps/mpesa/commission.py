"""Safaricom's commission for the agency: recorded once a month when it is paid, counted in the month it was earned.

Safaricom pays a month's commission early in the next month. The income belongs to the month the work was done, so
it is counted on that month's last day; until the money arrives it is owed by Safaricom ("Commission due from
Safaricom", 1160). When that month's books are already closed it is counted on the day it was paid instead, and the
entry says so. Money paid into the agency float or cash goes through the open shift, so the shift's balances and its
reconciliation show it; money paid anywhere else (your own M-Pesa, bank, cash) goes into the cash book. Nothing is
edited or deleted: a mistake is undone with a reason and recorded again.
"""
import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.accounting.ledger import cash_code, money, paired, post_journal, reverse_journal
from apps.tenancy.transactions import lock_business
from .models import MpesaCommissionEntry, MpesaOutlet, MpesaSession

AGENCY = {"AGENCY_FLOAT", "AGENCY_CASH"}
OUTSIDE = {"MPESA", "BANK", "CASH", "OTHER"}
LEGACY = {"FLOAT": "AGENCY_FLOAT"}
PLACES = [("AGENCY_FLOAT", "Agency float (moved into the working account)"), ("AGENCY_CASH", "Agency cash drawer (withdrawn as cash)"),
          ("MPESA", "Your own M-Pesa"), ("BANK", "Bank"), ("CASH", "Cash kept outside the agency"), ("OTHER", "Other")]


def month_start(day):
    return day.replace(day=1)


def month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _closed(day):
    from apps.accounting.models import FinancialPeriod
    return FinancialPeriod.objects.filter(start__lte=day, end__gte=day, closed=True).exists()


def _day(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValidationError("Enter dates as YYYY-MM-DD.")


def _open_shift(outlet, session_id=None):
    shifts = MpesaSession.objects.filter(outlet=outlet, status=MpesaSession.OPEN)
    if session_id:
        shifts = shifts.filter(pk=session_id)
    shift = shifts.first()
    if not shift:
        raise ValidationError(f"Open {outlet.display_name}'s shift first: commission moved into the agency float or cash goes "
                              "through the open shift so its balances stay right. Or choose where else it was paid.")
    return shift


@transaction.atomic
def record(*, outlet, user, period, amount, reference, settlement, key=None, paid_on=None, notes="", session_id=None):
    """Commission Safaricom paid for the month ``period`` falls in, received on ``paid_on`` (today if not given)."""
    lock_business()
    reference = " ".join(str(reference or "").split()).upper()[:100]  # optional: Safaricom often pays commission without a code
    key = str(key or reference or "").strip()
    existing = MpesaCommissionEntry.objects.filter(idempotency_key=key).first() if key else None
    if existing:
        return existing
    outlet = MpesaOutlet.objects.filter(pk=getattr(outlet, "pk", outlet)).first()
    if not outlet:
        raise ValidationError("Choose the agency outlet the commission is for.")
    value = money(amount)
    if value <= 0:
        raise ValidationError("Enter the commission Safaricom paid, above zero.")
    today = timezone.localdate()
    period, paid = _day(period), _day(paid_on) or today
    if not period:
        raise ValidationError("Choose the month the commission was earned in.")
    period = month_start(period)
    if period > month_start(today):
        raise ValidationError("Commission cannot be for a month that has not started.")
    if paid > today:
        raise ValidationError("The date it was paid cannot be in the future.")
    if paid < period:
        raise ValidationError("It cannot have been paid before the month it was earned in began.")
    if reference and MpesaCommissionEntry.objects.filter(reference=reference).exists():
        raise ValidationError(f"Commission with the reference {reference} is already recorded.")
    settlement = LEGACY.get(str(settlement or "").upper(), str(settlement or "").upper())
    if settlement not in AGENCY | OUTSIDE:
        raise ValidationError("Choose where Safaricom's money went: agency float, agency cash, your own M-Pesa, bank or cash.")
    if settlement in AGENCY and paid != today:
        raise ValidationError("Commission moved into the agency float or cash is recorded on the day it arrives, through the open shift.")
    # The month's income: on its last day, unless those books are closed (then on the day it was paid, and said so).
    earned_end = month_end(period)
    earned_on = earned_end if paid > earned_end and not _closed(earned_end) else paid
    paid_at = timezone.now() if paid == today else timezone.make_aware(datetime.combine(paid, time(12)))
    notes = str(notes or "").strip()
    if earned_on != earned_end and earned_on == paid and paid > earned_end:
        notes = (notes + " " if notes else "") + f"Counted on {paid:%d %b %Y} because {period:%B %Y}'s books were closed."
    agency = None
    if settlement in AGENCY:
        from .services import post_transaction
        shift = _open_shift(outlet, session_id)
        agency, _ = post_transaction(session=shift, transaction_type="COMMISSION", transaction_amount=value, user=user,
                                     idempotency_key=f"commission:{key}", provider_reference=reference or None,
                                     notes=f"Safaricom commission for {period:%B %Y}",
                                     cash_delta=value if settlement == "AGENCY_CASH" else 0, float_delta=value if settlement == "AGENCY_FLOAT" else 0)
    entry = MpesaCommissionEntry.objects.create(outlet=outlet, period=period, amount=value, reference=reference, settlement_method=settlement,
                                                recognized_at=paid_at, earned_on=earned_on, agency_transaction=agency, idempotency_key=key,
                                                recorded_by=user, notes=notes)
    branch = outlet.store_id
    # The shift already posted the float or cash against owner capital (3000); the commission replaces that.
    received = "3000" if agency else cash_code(settlement)
    words = f"Safaricom commission for {period:%B %Y}" + (f" ({reference})" if reference else "")
    if earned_on < paid:
        post_journal(key=f"commission-earned:{entry.pk}", description=f"{words}, earned", branch=branch, date=earned_on, user=user,
                     lines=paired("1160", "4010", value))
        post_journal(key=f"commission:{entry.pk}", description=f"{words}, paid", branch=branch, date=paid, user=user,
                     lines=paired(received, "1160", value))
    else:
        post_journal(key=f"commission:{entry.pk}", description=words, branch=branch, date=paid, user=user, lines=paired(received, "4010", value))
    if not agency:
        from apps.accounting.services import post
        post(unit="MPESA", method=settlement, amount=value, kind="INCOME", reference=reference or f"Commission {period:%b %Y}", key=f"commission:{entry.pk}", user=user,
             occurred_at=paid_at, branch=outlet.store, journal=False)
    from apps.core.models import AuditLog
    AuditLog.objects.create(action="MPESA_COMMISSION_RECORDED", object_type="MpesaCommissionEntry", object_id=str(entry.pk), user=user,
                            after={"amount": str(value), "reference": reference, "period": str(period), "earned_on": str(earned_on),
                                   "paid_on": str(paid), "settlement": settlement})
    return entry


@transaction.atomic
def undo(*, entry, user, reason):
    """Commission recorded by mistake: its income, the money and anything owed by Safaricom all come back out."""
    lock_business()
    entry = MpesaCommissionEntry.objects.select_for_update(of=("self",)).select_related("agency_transaction").get(pk=entry.pk)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Say why this commission is being undone.")
    if entry.reversed_at:
        return entry
    if entry.agency_transaction_id:
        from .services import reverse_transaction
        if entry.agency_transaction.session.status != MpesaSession.OPEN:
            raise ValidationError("The shift this commission went into has closed, so its float or cash can no longer be changed. "
                                  "If the amount was wrong, record the difference with the next commission.")
        reverse_transaction(original=entry.agency_transaction, user=user, idempotency_key=f"commission-undo:{entry.pk}", reason=reason,
                            allow_commission=True)
        _reverse_journals(entry, user, reason)
        mark_undone(entry, reason)
    else:
        from apps.accounting.models import CashEntry
        from apps.accounting.services import reverse
        cash = CashEntry.objects.filter(source_key=f"commission:{entry.pk}").first()
        if cash and not CashEntry.objects.filter(reversal_of=cash).exists():
            reverse(entry=cash, user=user, reason=reason)  # reverses the journals and marks the entry undone
        else:
            _reverse_journals(entry, user, reason)
            mark_undone(entry, reason)
    entry.refresh_from_db()
    return entry


def _reverse_journals(entry, user, reason):
    from apps.accounting.models import JournalEntry
    for key, undo_key in [(f"commission:{entry.pk}", f"commission-reversal:{entry.pk}"), (f"commission-earned:{entry.pk}", f"commission-earned-reversal:{entry.pk}")]:
        journal = JournalEntry.objects.filter(source_key=key).first()
        if journal and not JournalEntry.objects.filter(reversal_of=journal).exists():
            reverse_journal(journal, user=user, reason=reason, key=undo_key)


def mark_undone(entry, reason):
    MpesaCommissionEntry.objects.filter(pk=entry.pk, reversed_at__isnull=True).update(reversed_at=timezone.now(), reverse_reason=reason)


def earned_by_month(start=None):
    """{first day of month: commission} for commission not undone, by the month it was earned."""
    rows = MpesaCommissionEntry.objects.filter(reversed_at__isnull=True)
    if start:
        rows = rows.filter(period__gte=start)
    return {row["month"]: row["v"] for row in rows.values(month=TruncMonth("period")).annotate(v=Sum("amount"))}


def due_month(today=None):
    """Last month, when the agency worked then (a shift was open) and no commission is recorded for it yet; else None."""
    today = today or timezone.localdate()
    last = month_start(month_start(today) - timedelta(days=1))
    worked = MpesaSession.objects.filter(opened_at__date__lte=month_end(last)).exclude(closed_at__date__lt=last).exists()
    if not worked:
        return None
    if MpesaCommissionEntry.objects.filter(period=last, reversed_at__isnull=True).exists():
        return None
    return last


def monthly_profit(months=12, today=None):
    """The agency month by month: commission earned, its running costs and what is left (profit or loss)."""
    from apps.accounting.models import Expense, JournalEntry
    today = today or timezone.localdate()
    first = month_start(today)
    for _ in range(months - 1):
        first = month_start(first - timedelta(days=1))
    earned = earned_by_month(first)
    cancelled = set(JournalEntry.objects.filter(source_key__startswith="expense-cancel:").values_list("source_key", flat=True))
    costs = {}
    for expense in Expense.objects.filter(business_unit="MPESA", incurred_on__gte=first).only("pk", "amount", "incurred_on"):
        if f"expense-cancel:{expense.pk}" in cancelled:
            continue
        month = month_start(expense.incurred_on)
        costs[month] = costs.get(month, Decimal("0")) + expense.amount
    rows, month = [], first
    while month <= month_start(today):
        commission, cost = earned.get(month, Decimal("0")), costs.get(month, Decimal("0"))
        rows.append({"month": month, "commission": commission, "expenses": cost, "profit": commission - cost})
        month = month_start(month_end(month) + timedelta(days=1))
    return rows
