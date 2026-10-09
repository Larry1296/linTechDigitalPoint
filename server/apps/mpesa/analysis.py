"""How the M-Pesa agency has been doing, for the desk's Analysis: day by day over the last working days, the busiest
hours, the sizes of transactions, and which kind earns the commission. Reversed transactions and their reversals are
left out; commission is what the app measured or learned (commission_learning.py). Sundays are left out: the agency
does not open on Sundays."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .commission_learning import EARNING, SUNDAY, earned, learn

ZERO = Decimal("0")
KINDS = {"CUSTOMER_DEPOSIT": "deposits", "CUSTOMER_WITHDRAWAL": "withdrawals", "AIRTIME_SALE": "airtime"}
SIZES = [(Decimal("100"), "Up to 100"), (Decimal("500"), "101 to 500"), (Decimal("1000"), "501 to 1,000"), (Decimal("2500"), "1,001 to 2,500"),
         (Decimal("5000"), "2,501 to 5,000"), (Decimal("10000"), "5,001 to 10,000"), (None, "Over 10,000")]


def working_days(end, count):
    """The last ``count`` days up to ``end`` the agency opens on, oldest first."""
    days, day = [], end
    while len(days) < count:
        if day.weekday() != SUNDAY:
            days.append(day)
        day -= timedelta(days=1)
    return days[::-1]


def analysis(outlet_ids=None, days=30):
    today = timezone.localdate()
    span = working_days(today, days)
    outlets, measured, rates = learn(outlet_ids)
    results = earned(outlets, measured, rates)
    rows = [r for rows in outlets.values() for r in rows if r.standing and timezone.localtime(r.done_at).date() >= span[0]]
    by_day = {day: {"date": day, "deposits": ZERO, "withdrawals": ZERO, "airtime": ZERO, "count": 0, "commission": ZERO} for day in span}
    hours = defaultdict(int)
    sizes = defaultdict(int)
    commission = {kind: ZERO for kind in KINDS.values()}
    unknown = 0
    for row in rows:
        moment = timezone.localtime(row.done_at)
        day = by_day.get(moment.date())
        if day is None:
            continue  # a Sunday
        kind = KINDS[row.transaction_type]
        value, _ = results.get(row.pk, (None, None))
        day[kind] += row.amount
        day["count"] += 1
        hours[moment.hour] += 1
        sizes[next(label for limit, label in SIZES if limit is None or row.amount <= limit)] += 1
        if value is None:
            unknown += 1
        else:
            day["commission"] += value
            commission[kind] += value
    busy = sorted(hours)
    return {"days": list(by_day.values()), "working_days": len(span), "unknown": unknown,
            "hours": [{"hour": hour, "count": hours[hour]} for hour in range(busy[0], busy[-1] + 1)] if busy else [],
            "sizes": [{"label": label, "count": sizes[label]} for _, label in SIZES],
            "commission_by_kind": [{"kind": kind, "amount": amount} for kind, amount in commission.items()],
            "kinds": list(EARNING)}
