"""Weekly shifts and surprise money checks.

A shift runs the agency's working week, Monday to Saturday (the agency is closed on Sundays). It is opened on the week's
first working day and closed on its Saturday with a full count. In between, the cash and float are not counted every
evening; instead the shift is checked by surprise: when it opens, CHECKS_PER_WEEK working days between the opening day
and the closing day are picked at random, each with a random time in working hours. Nobody is shown when they fall.
When one comes due, whoever is on the desk counts the cash and reads the float, and the count is compared with what the
records say. The owner can also check at any time.

The figure that must agree is the total money in operation, cash plus float: deposits and withdrawals only swap one for
the other. A split that differs while the total agrees is shown too, since it usually means a deposit or withdrawal was
not recorded or was recorded the wrong way round.
"""
import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.tenancy.permissions import is_business_manager, is_employee

from .models import MpesaMoneyCheck, MpesaSession

SUNDAY = 6
SATURDAY = 5
CHECKS_PER_WEEK = 2
# Surprise checks fall between these hours, local time, so the desk is open when they come due.
CHECK_HOURS = (9, 17)


def week_end(day):
    """The Saturday a shift opened on ``day`` runs until: that week's, or next week's when opened on a Saturday or Sunday
    (a shift opened on the week's last day is the next week's)."""
    if day.weekday() >= SATURDAY:
        day += timedelta(days=7 - day.weekday())  # the Monday after
    return day + timedelta(days=SATURDAY - day.weekday())


def check_days(opened_on, runs_until):
    """The working days a surprise check can fall on: after the opening count and before the closing one."""
    day, days = opened_on + timedelta(days=1), []
    while day < runs_until:
        if day.weekday() != SUNDAY:
            days.append(day)
        day += timedelta(days=1)
    return days


def schedule(session):
    """Set the shift's last day and its surprise checks. Called when the shift opens."""
    opened_on = timezone.localdate(session.opened_at)
    session.runs_until = week_end(opened_on)
    session.save(update_fields=["runs_until", "updated_at"])
    chance = secrets.SystemRandom()
    days = check_days(opened_on, session.runs_until)
    zone = timezone.get_current_timezone()
    for day in sorted(chance.sample(days, min(CHECKS_PER_WEEK, len(days)))):
        minute = chance.randrange(CHECK_HOURS[0] * 60, CHECK_HOURS[1] * 60)
        moment = timezone.make_aware(datetime.combine(day, time(minute // 60, minute % 60)), zone)
        MpesaMoneyCheck.objects.create(session=session, due_at=moment)


def due_check(session, now=None):
    """The surprise check waiting to be counted now, if any: the earliest one whose time has come."""
    if session is None or session.status != MpesaSession.OPEN:
        return None
    return session.money_checks.filter(counted_at__isnull=True, due_at__lte=now or timezone.now()).order_by("due_at").first()


def checks_left(session):
    """How many surprise checks are still to come this week (never when)."""
    return session.money_checks.filter(counted_at__isnull=True, due_at__gt=timezone.now()).count()


def check_row(check, *, money=True):
    """A counted check as the page shows it; ``money`` False leaves out every figure (an employee's view)."""
    row = {"id": check.pk, "due_at": check.due_at, "counted_at": check.counted_at, "surprise": check.due_at is not None,
           "counted_by": (check.counted_by.get_full_name() or check.counted_by.username) if check.counted_by_id else ""}
    if money and check.counted_at:
        split = (check.cash - check.expected_cash) if check.difference == 0 else Decimal("0")
        row.update({"cash": check.cash, "float": check.float, "total": check.cash + check.float, "expected_cash": check.expected_cash,
                    "expected_float": check.expected_float, "expected_total": check.expected_cash + check.expected_float,
                    "difference": check.difference, "split_off": split, "reason": check.reason})
    return row


@transaction.atomic
def count(*, session, user, actual_cash, actual_float, cash_count=None, reason="", check_id=None):
    """Record a money check on the open shift: the surprise check that is due, or the owner's own check at any time.

    An employee counts blind, as at the close: they never see what was expected, and a difference is recorded for the
    owner to follow up. The owner gives a reason when the total differs."""
    from .services import audit, counted_cash, on_shift, session_balances
    session = MpesaSession.objects.select_for_update().get(pk=session.pk)
    if session.status != MpesaSession.OPEN:
        raise ValidationError("The shift is closed: its money was counted at the close.")
    if not on_shift(user, session):
        raise ValidationError("You can only check the money on your own shift.")
    check = due_check(session) if check_id in (None, "") else session.money_checks.filter(pk=check_id).first()
    if check_id not in (None, "") and (check is None or check.counted_at or (check.due_at and check.due_at > timezone.now())):
        raise ValidationError("That money check is not waiting to be counted.")
    if check is None:
        if not is_business_manager(user):
            raise ValidationError("No money check is due now. The business owner is told when one comes due.")
        check = MpesaMoneyCheck(session=session)  # the owner's own check
    cash, normalised = counted_cash(actual_cash, cash_count)
    try:
        electronic_float = Decimal(str(actual_float).replace(",", "").strip()).quantize(Decimal("0.01"))
    except Exception:
        raise ValidationError("Enter the float on the M-Pesa line as an amount.")
    if cash < 0 or electronic_float < 0:
        raise ValidationError("The cash and float cannot be negative.")
    expected_cash, expected_float = session_balances(session)
    difference = (cash + electronic_float) - (expected_cash + expected_float)
    reason = str(reason or "").strip()
    if difference and not reason:
        if is_employee(user):
            reason = f"Counted by {user.get_full_name() or user.username}: the total differs from the records, for the owner to check."
        else:
            raise ValidationError(f"The money counted is {difference:+,.2f} against the records. Say why, for example a transaction not recorded yet.")
    check.counted_at, check.counted_by, check.cash, check.float = timezone.now(), user, cash, electronic_float
    check.expected_cash, check.expected_float, check.cash_count, check.reason = expected_cash, expected_float, normalised, reason
    check.save()
    audit("MPESA_MONEY_CHECK", check, user, after={"difference": f"{difference:.2f}", "cash_variance": f"{cash - expected_cash:.2f}",
                                                    "float_variance": f"{electronic_float - expected_float:.2f}", "surprise": check.due_at is not None,
                                                    "reason": reason})
    return check
