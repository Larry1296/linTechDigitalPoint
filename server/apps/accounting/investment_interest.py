"""The fund's interest rate, recorded once a month, and what the money is estimated to have earned since the last statement.

Money market funds such as CIC's quote a yearly rate and work interest out every day on the balance (rate ÷ 365), adding
it to the account at the end of each month after withholding tax (15% in Kenya), so it earns interest from then on.
The estimate follows the same rule using the rates recorded here. It is only a guide: the books change only when a
statement balance is recorded, and the difference from what the app expects becomes interest (see investments.py).
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.tenancy.transactions import lock_business
from .investments import SIGN, record_statement, value
from .ledger import money
from .models import Investment, InvestmentMovement, InvestmentRate
from .services import audit

ZERO = Decimal("0")
CENT = Decimal("0.01")


def month_of(day):
    return day.replace(day=1)


def current_rate(investment):
    return investment.rates.order_by("-month").first()


def rate_now(investment, today=None):
    """The yearly rate the money earns today, or None: the fund's published rate for an account that follows one."""
    rates = timeline(investment)
    return _rate_for(rates, today or timezone.localdate()) if rates else None


def due(investment, today=None):
    """True when the investment holds money and nobody has recorded this month's rate yet.

    An account that follows a fund's published rate is never due while that rate is current: the app keeps it up.
    """
    today = today or timezone.localdate()
    if value(investment) <= 0:
        return False
    if investment.fund:
        from .fund_rates import is_fresh, latest
        if is_fresh(latest(investment.fund)):
            return False
    return not investment.rates.filter(month=month_of(today)).exists()


def timeline(investment):
    """[(from_date, yearly rate)], oldest first: the rates typed in for each month and, for an account that follows a
    fund, every rate the fund published from its own date (so a change mid-month counts from the right day)."""
    published = []
    if investment.fund:
        from .fund_rates import history
        published = history(investment.fund)
    monthly = investment.rates.order_by("month")
    if published:
        monthly = monthly.filter(automatic=False)  # the fund's own dated rates replace the copies written into each month
    # On the same date a published rate comes after (and so wins over) a month's typed-in rate.
    rows = [(r.month, 0, r.annual_rate) for r in monthly] + [(day, 1, rate) for day, rate in published]
    return [(day, rate) for day, _, rate in sorted(rows, key=lambda row: (row[0], row[1]))]


def earnings(balance, annual_rate, tax_rate):
    """What a balance earns at a yearly rate: a day, an average month and a year, before and after withholding tax.

    Interest is worked out daily (rate ÷ 365) and added each month end after tax, so over a year it earns interest on
    its own interest: the year is twelve months compounded on the after-tax interest, as the fund pays it.
    """
    balance, rate = Decimal(balance or 0), Decimal(annual_rate or 0) / 100
    keep = 1 - Decimal(tax_rate or 0) / 100

    def split(gross):
        gross = gross.quantize(CENT)
        net = (gross * keep).quantize(CENT)
        return {"gross": gross, "tax": gross - net, "net": net}
    year_net = balance * ((1 + rate / 12 * keep) ** 12 - 1)
    return {"balance": balance.quantize(CENT), "annual_rate": Decimal(annual_rate or 0), "day": split(balance * rate / 365),
            "month": split(balance * rate / 12), "year": split(year_net / keep if keep else balance * rate)}


def _rate_for(rates, day):
    """The rate recorded for the day's month, else the latest before it, else the earliest known."""
    chosen = rates[0][1]
    for month, rate in rates:
        if month <= day:
            chosen = rate
    return chosen


def estimate(investment, today=None):
    """Interest estimated to have built up since the money was last checked against a statement, or None without a rate.

    {since, days, rate, gross, tax, net, value}: value is what the app records now plus the estimated interest after tax.
    """
    today = today or timezone.localdate()
    rates = timeline(investment)
    live = list(investment.movements.filter(reversed_at__isnull=True).order_by("occurred_on", "pk"))
    if not rates or not live:
        return None
    # The last time the app's figure was set from a statement: a statement that changed it, or a check that agreed with it.
    checks = [m.occurred_on for m in live if m.kind in {InvestmentMovement.INTEREST, InvestmentMovement.FEE}]
    checks += list(investment.rates.filter(statement_balance__isnull=False).values_list("recorded_on", flat=True))
    since = max(checks) if checks else live[0].occurred_on
    since = min(since, today)
    changes = {}
    balance = ZERO
    for m in live:
        if m.occurred_on <= since:
            balance += SIGN[m.kind] * m.amount
        else:
            changes[m.occurred_on] = changes.get(m.occurred_on, ZERO) + SIGN[m.kind] * m.amount
    keep = 1 - investment.tax_rate / 100
    gross = credited = month_gross = ZERO
    day = since
    while day < today:
        day += timedelta(days=1)
        balance += changes.get(day, ZERO)
        if balance + credited > 0:
            month_gross += (balance + credited) * _rate_for(rates, day) / 100 / 365
        if day.day == calendar.monthrange(day.year, day.month)[1]:
            # Interest is added at the end of the month, after tax, and earns interest itself from then on.
            gross += month_gross
            credited += month_gross * keep
            month_gross = ZERO
    gross += month_gross
    gross = gross.quantize(CENT)
    net = (gross * keep).quantize(CENT)
    return {"since": since, "days": (today - since).days, "rate": _rate_for(rates, today), "gross": gross,
            "tax": gross - net, "net": net, "value": (value(investment) + net).quantize(CENT)}


@transaction.atomic
def record_month(*, investment, user, annual_rate, key, balance=None, note=""):
    """This month's check: the rate the fund quotes now and, if known, the balance it shows.

    A balance different from what the app expects is recorded as interest (or fees) from the statement. Recording the
    rate again in the same month corrects it.
    """
    lock_business()
    investment = Investment.objects.select_for_update().get(pk=investment.pk)
    rate = Decimal(str(annual_rate)).quantize(Decimal("0.001"))
    if rate < 0 or rate > 100:
        raise ValidationError("Enter the yearly rate as a percentage between 0 and 100, e.g. 13.25.")
    today = timezone.localdate()
    note = str(note or "").strip()
    if balance not in (None, ""):
        balance = money(balance)
        if balance != value(investment):
            record_statement(investment=investment, user=user, balance=balance, key=f"{key}:statement", occurred_on=today,
                             note=note or "Monthly check")
    else:
        balance = None
    existing = investment.rates.filter(month=month_of(today)).first()
    if existing:
        InvestmentRate.objects.filter(pk=existing.pk).update(
            annual_rate=rate, recorded_on=today, note=note, created_by=user,
            statement_balance=balance if balance is not None else existing.statement_balance)
        audit(investment, user, f"{investment.name} rate for {today:%B %Y} corrected from {existing.annual_rate}% to {rate}%")
        existing.refresh_from_db()
        return existing
    record = InvestmentRate.objects.create(investment=investment, month=month_of(today), annual_rate=rate, statement_balance=balance,
                                           recorded_on=today, note=note, created_by=user)
    audit(investment, user, f"{investment.name} rate for {today:%B %Y}: {rate}% a year")
    return record


def first_rate(*, investment, user, annual_rate):
    """The rate given when the account is added, so estimates can start straight away."""
    if annual_rate in (None, ""):
        return None
    return record_month(investment=investment, user=user, annual_rate=annual_rate, key=f"opening-rate:{investment.pk}")


def month_label(day):
    return date(day.year, day.month, 1).strftime("%B %Y")
