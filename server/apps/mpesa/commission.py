"""Safaricom's commission for the agency: recorded once a month when it is paid, counted in the month it was earned.

Safaricom pays a month's commission early in the next month. The income belongs to the month the work was done, so
it is counted on that month's last day; until the money arrives it is owed by Safaricom ("Commission due from
Safaricom", 1160). When that month's books are already closed it is counted on the day it was paid instead, and the
entry says so. Money paid into the agency float or cash goes through the open shift, so the shift's balances and its
reconciliation show it; money paid anywhere else (your own M-Pesa, bank, cash) goes into the cash book. Nothing is
edited or deleted: a mistake is undone with a reason and recorded again.

Where the money went, during a shift:
- AGENCY_FLOAT: kept in the float, which goes up by the commission.
- AGENCY_FLOAT_TO_OWNER: paid into the float, and the owner took the same amount out of the drawer as cash, like a
  withdrawal: the float goes up, the drawer goes down, and the cash is the business's, kept outside the agency.
- AGENCY_CASH: put into the agency drawer as cash.
Between shifts (OPENING_FLOAT): Safaricom paid it after one shift closed and the next shift's opening float already
counted it. Nothing in the float changes; the commission is recorded against that shift, and only up to how much more
float it opened with than the previous shift closed with, so the same money is never counted as commission twice.
"""
import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.accounting.ledger import cash_code, money, paired, post_journal, reverse_journal
from apps.tenancy.transactions import lock_business
from .models import MpesaCommissionEntry, MpesaOutlet, MpesaSession

AGENCY = {"AGENCY_FLOAT", "AGENCY_FLOAT_TO_OWNER", "AGENCY_CASH"}
OPENING = "OPENING_FLOAT"
OUTSIDE = {"MPESA", "BANK", "CASH", "OTHER"}
LEGACY = {"FLOAT": "AGENCY_FLOAT"}
PLACES = [("AGENCY_FLOAT", "Kept in the agency float (the float goes up)"),
          ("AGENCY_FLOAT_TO_OWNER", "Paid into the float, owner took it from the drawer as cash"),
          ("AGENCY_CASH", "Put into the agency cash drawer"),
          (OPENING, "Already in the float when a shift opened"),
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


def previous_close(outlet, before=None):
    """The outlet's last closed shift (before ``before``, a moment), whose counted cash and float the next shift opens with."""
    shifts = MpesaSession.objects.filter(outlet=outlet, status=MpesaSession.CLOSED, closing_float_actual__isnull=False)
    if before:
        shifts = shifts.filter(closed_at__lte=before)
    return shifts.order_by("-closed_at", "-pk").first()


def opening_room(shift):
    """How much of ``shift``'s opening float can still be commission: what it opened with above the previous shift's
    closing float (all of it for the first shift), less commission already recorded against it."""
    carried = shift.carried_float
    if carried is None:
        last = previous_close(shift.outlet_id, shift.opened_at)
        carried = last.closing_float_actual if last else Decimal("0")
    taken = MpesaCommissionEntry.objects.filter(opening_session=shift, reversed_at__isnull=True).aggregate(v=Sum("amount"))["v"] or 0
    return max(Decimal("0"), shift.opening_float - carried - taken)


def _opening_shift(outlet, session_id):
    shift = MpesaSession.objects.filter(pk=session_id, outlet=outlet).first() if session_id else None
    if not shift:
        raise ValidationError("Choose the shift whose opening float already had the commission in it.")
    return shift


SPENT_FROM = "MPESA"  # commission spent straight away passes through the owner's M-Pesa: in, then out to each cost


def _spent_lines(spent):
    """[(category name, description, amount, unit)] for the parts of a commission spent straight away; each is a cost."""
    from apps.accounting.models import BusinessUnit
    lines = []
    for item in spent or []:
        category = " ".join(str(item.get("category") or "").split())[:120]
        description = " ".join(str(item.get("description") or "").split())[:500]
        unit = str(item.get("unit") or "MPESA").upper()
        value = money(item.get("amount"))
        if value <= 0:
            raise ValidationError("Each amount spent from the commission must be above zero.")
        if not category or not description:
            raise ValidationError("Say what each amount spent from the commission was for: a type (e.g. Rent) and a few words.")
        if unit not in BusinessUnit.values:
            raise ValidationError("Choose which part of the business each cost belongs to.")
        lines.append((category, description, value, unit))
    return lines


@transaction.atomic
def record(*, outlet, user, period, amount, reference, settlement, key=None, paid_on=None, notes="", session_id=None, spent=None):
    """Commission Safaricom paid for the month ``period``. Any part of it spent straight away (``spent``: what on, how
    much, for which part of the business) is recorded as those costs; the rest goes where ``settlement`` says.

    The whole amount is the agency's income for that month either way, and each cost counts against profit, so the
    month's profit or loss is right however the money was used. The spent part is recorded as its own commission entry
    paid into the owner's M-Pesa and paid straight out again for the costs, so the money's trail is complete."""
    lock_business()
    key = str(key or "").strip()
    lines = _spent_lines(spent)
    total = money(amount)
    used = sum((line[2] for line in lines), Decimal("0"))
    if not lines:
        return _record_part(outlet=outlet, user=user, period=period, amount=amount, reference=reference, settlement=settlement,
                            key=key, paid_on=paid_on, notes=notes, session_id=session_id)
    if used > total:
        raise ValidationError(f"More was spent ({used:,.2f}) than Safaricom paid ({total:,.2f}).")
    kept = total - used
    main = None
    if kept > 0:
        main = _record_part(outlet=outlet, user=user, period=period, amount=kept, reference=reference, settlement=settlement,
                            key=key, paid_on=paid_on, notes=notes, session_id=session_id)
        paid_on = timezone.localtime(main.recognized_at).date()
    words = "; ".join(f"{description} ({value:,.2f})" for _, description, value, _ in lines)
    part = _record_part(outlet=outlet, user=user, period=period, amount=used, reference="" if main else reference, settlement=SPENT_FROM,
                        key=f"{key}:spent" if key else None, paid_on=paid_on,
                        notes=(f"Spent straight from the commission: {words}." + (f" {notes}" if notes and not main else "")).strip())
    from apps.accounting.models import ExpenseCategory
    from apps.accounting.services import record_expense
    for number, (category, description, value, unit) in enumerate(lines, start=1):
        kind = ExpenseCategory.objects.filter(name__iexact=category).first() or ExpenseCategory.objects.create(name=category)
        record_expense(user=user, category=kind, unit=unit, method=SPENT_FROM, amount=value, key=f"commission-spent:{part.pk}:{number}",
                       description=f"{description} (paid from {period:%B %Y} commission)", incurred_on=timezone.localtime(part.recognized_at).date())
    return main or part


def _record_part(*, outlet, user, period, amount, reference, settlement, key=None, paid_on=None, notes="", session_id=None):
    """Commission Safaricom paid for the month ``period`` falls in, received on ``paid_on`` (today if not given)."""
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
    settlement = LEGACY.get(str(settlement or "").upper(), str(settlement or "").upper())
    if settlement not in AGENCY | OUTSIDE | {OPENING}:
        raise ValidationError("Choose where Safaricom's money went: agency float, agency cash, your own M-Pesa, bank or cash.")
    opening = _opening_shift(outlet, session_id) if settlement == OPENING else None
    if opening:
        paid_on = timezone.localtime(opening.opened_at).date()  # it was in the float when that shift opened
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
    if opening:
        room = opening_room(opening)
        if value > room:
            raise ValidationError(f"That shift opened with {room:,.2f} more float than the shift before it closed with (after commission "
                                  "already recorded against it), so at most that much of it can be commission.")
    if settlement in AGENCY and paid != today:
        raise ValidationError("Commission moved into the agency float or cash is recorded on the day it arrives, through the open shift.")
    # The month's income: on its last day, unless those books are closed (then on the day it was paid, and said so).
    earned_end = month_end(period)
    earned_on = earned_end if paid > earned_end and not _closed(earned_end) else paid
    paid_at = timezone.now() if paid == today else timezone.make_aware(datetime.combine(paid, time(12)))
    notes = str(notes or "").strip()
    if earned_on != earned_end and earned_on == paid and paid > earned_end:
        notes = (notes + " " if notes else "") + f"Counted on {paid:%d %b %Y} because {period:%B %Y}'s books were closed."
    if opening:
        notes = (notes + " " if notes else "") + f"Already in the float when the shift of {paid:%d %b %Y} opened."
    agency = None
    if settlement in AGENCY:
        from .services import post_transaction
        shift = _open_shift(outlet, session_id)
        to_owner = settlement == "AGENCY_FLOAT_TO_OWNER"
        cash_delta = value if settlement == "AGENCY_CASH" else -value if to_owner else 0
        agency, _ = post_transaction(session=shift, transaction_type="COMMISSION", transaction_amount=value, user=user,
                                     idempotency_key=f"commission:{key}", provider_reference=reference or None,
                                     notes=f"Safaricom commission for {period:%B %Y}" + (", taken from the drawer as cash" if to_owner else ""),
                                     cash_delta=cash_delta, float_delta=0 if settlement == "AGENCY_CASH" else value)
    entry = MpesaCommissionEntry.objects.create(outlet=outlet, period=period, amount=value, reference=reference, settlement_method=settlement,
                                                recognized_at=paid_at, earned_on=earned_on, agency_transaction=agency, idempotency_key=key,
                                                recorded_by=user, notes=notes, opening_session=opening)
    branch = outlet.store_id
    # The shift posted the float or cash against owner capital (3000), as the books do with the money in a shift's
    # opening counts; the commission is where that money came from. Taken from the drawer as cash, the shift's float
    # and cash cancel out and the money is the business's cash outside the agency.
    outside = "CASH" if settlement == "AGENCY_FLOAT_TO_OWNER" else settlement if settlement in OUTSIDE else None
    received = cash_code(outside) if outside else "3000"
    words = f"Safaricom commission for {period:%B %Y}" + (f" ({reference})" if reference else "")
    if earned_on < paid:
        post_journal(key=f"commission-earned:{entry.pk}", description=f"{words}, earned", branch=branch, date=earned_on, user=user,
                     lines=paired("1160", "4010", value))
        post_journal(key=f"commission:{entry.pk}", description=f"{words}, paid", branch=branch, date=paid, user=user,
                     lines=paired(received, "1160", value))
    else:
        post_journal(key=f"commission:{entry.pk}", description=words, branch=branch, date=paid, user=user, lines=paired(received, "4010", value))
    if outside:
        from apps.accounting.services import post
        post(unit="MPESA", method=outside, amount=value, kind="INCOME", reference=reference or f"Commission {period:%b %Y}", key=f"commission:{entry.pk}", user=user,
             occurred_at=paid_at, branch=outlet.store, journal=False)
    from apps.core.models import AuditLog
    AuditLog.objects.create(action="MPESA_COMMISSION_RECORDED", object_type="MpesaCommissionEntry", object_id=str(entry.pk), user=user,
                            after={"amount": str(value), "reference": reference, "period": str(period), "earned_on": str(earned_on),
                                   "paid_on": str(paid), "settlement": settlement, "opening_session": opening.pk if opening else None})
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
    from apps.accounting.models import CashEntry, Expense
    from apps.accounting.services import cancel_expense, reverse
    for cost in Expense.objects.filter(idempotency_key__startswith=f"commission-spent:{entry.pk}:"):
        cancel_expense(expense=cost, user=user, reason=reason)  # what was paid from this commission comes out of the costs too
    cash = CashEntry.objects.filter(source_key=f"commission:{entry.pk}").first()
    if cash and not CashEntry.objects.filter(reversal_of=cash).exists():
        reverse(entry=cash, user=user, reason=reason)  # reverses the journals and marks the entry undone
    else:
        _reverse_journals(entry, user, reason)
        mark_undone(entry, reason)
    entry.refresh_from_db()
    if entry.idempotency_key:
        # Undoing a payment undoes the part of it that was spent straight away, recorded alongside it.
        for part in MpesaCommissionEntry.objects.filter(idempotency_key=f"{entry.idempotency_key}:spent", reversed_at__isnull=True):
            undo(entry=part, user=user, reason=reason)
    return entry


def _reverse_journals(entry, user, reason):
    from apps.accounting.models import JournalEntry
    for key, undo_key in [(f"commission:{entry.pk}", f"commission-reversal:{entry.pk}"), (f"commission-earned:{entry.pk}", f"commission-earned-reversal:{entry.pk}")]:
        journal = JournalEntry.objects.filter(source_key=key).first()
        if journal and not JournalEntry.objects.filter(reversal_of=journal).exists():
            # Undone on the day it was counted, so the month it was earned in no longer shows it and today's sales
            # are not reduced by it; only when that period's books are closed does the undo count today.
            day = None if _closed(journal.posting_date) else journal.posting_date
            reverse_journal(journal, user=user, reason=reason, key=undo_key, date=day)


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
    # The agency's own costs, and its share of costs shared with the other parts of the business (such as rent).
    agency = Q(business_unit="MPESA", unit_shares={}) | Q(unit_shares__has_key="MPESA")
    for expense in Expense.objects.filter(agency, incurred_on__gte=first).only("pk", "amount", "incurred_on", "business_unit", "unit_shares"):
        if f"expense-cancel:{expense.pk}" in cancelled:
            continue
        month = month_start(expense.incurred_on)
        costs[month] = costs.get(month, Decimal("0")) + expense.shares().get("MPESA", Decimal("0"))
    rows, month = [], first
    while month <= month_start(today):
        commission, cost = earned.get(month, Decimal("0")), costs.get(month, Decimal("0"))
        rows.append({"month": month, "commission": commission, "expenses": cost, "profit": commission - cost})
        month = month_start(month_end(month) + timedelta(days=1))
    return rows
