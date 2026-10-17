"""Each part of the business on its own: the shop, cyber and the M-Pesa agency each keep their own books.

What it sold (for the agency, the commission it earned), what the sold items cost, its running costs (a cost shared
between the parts counts by each part's share), its profit or loss, month by month, and its own money: what it brought into
the owner's places, less what it paid out from there (for the agency, its own cash and float). The dashboard brings
together only the parts' profit. The dashboard adds the parts together for the whole business; each part's page shows these.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

ZERO = Decimal("0")
FIELDS = ("revenue", "cogs", "expenses", "stock_corrections", "profit")


def part_money(key):
    """{"amount", "places"}: the part's own money now, and where it is ([{"label", "amount"}])."""
    from apps.accounting.money_check import places
    from .dashboard_summary import agency_money
    where = [{"label": place["label"], "amount": row["amount"]} for place in places() for row in place["by_part"]
             if row["unit"] == key and row["amount"]]
    if key == "MPESA" and (agency := agency_money()):
        where = [{"label": "Agency cash", "amount": agency["cash"]}, {"label": "Agency float", "amount": agency["float"]}, *where]
    return {"amount": sum((row["amount"] for row in where), ZERO), "places": where}


def money_after(moments):
    """Each part's own money right after each moment, from the cash book: {key: amount} for ``moments`` given as
    {key: (part, moment)}, e.g. the shop's money right after a sale and its payments."""
    from bisect import bisect_right
    from apps.accounting.models import CashEntry
    from apps.accounting.money_check import PLACES
    series = {}
    for unit in {unit for unit, _ in moments.values()}:
        entries = CashEntry.objects.filter(business_unit=unit, account__payment_method__in=[method for method, _ in PLACES])
        times, running, total = [], [], ZERO
        for at, value in entries.order_by("occurred_at", "pk").values_list("occurred_at", "amount"):
            total += value
            times.append(at)
            running.append(total)
        series[unit] = (times, running)
    result = {}
    for key, (unit, moment) in moments.items():
        times, running = series[unit]
        index = bisect_right(times, moment)
        result[key] = running[index - 1] if index else ZERO
    return result


def _count(key):
    from apps.commerce.models import Sale
    if key == "SHOP":
        return Sale.objects.filter(status="COMPLETED", channel__in=[Sale.POS, Sale.ONLINE]).count()
    if key == "CYBER":
        from apps.cyber.models import CyberJob
        return CyberJob.objects.filter(completed_at__isnull=False, sale__status="COMPLETED").count()
    from apps.mpesa.models import MpesaTransaction
    return MpesaTransaction.objects.filter(status="POSTED", reversal_of__isnull=True, reversal__isnull=True,
                                           transaction_type__in=["CUSTOMER_DEPOSIT", "CUSTOMER_WITHDRAWAL", "AIRTIME_SALE"]).count()


def part_books(key, *, profit_visible, money_visible):
    from apps.accounting.money_mode import part_names
    from .dashboard import accrual_totals, pnl_rows
    rows = [row for row in pnl_rows(date(1900, 1, 1), date(9999, 12, 31)) if row["unit"] == key]
    ever = accrual_totals(rows, [key])
    today = timezone.localdate()
    first = date(today.year - (1 if today.month < 12 else 0), (today.month % 12) + 1, 1)  # the last twelve months
    months = {}
    for row in rows:
        month = row["date"].replace(day=1)
        if month >= first:
            months.setdefault(month, []).append(row)
    trend = []
    for month in sorted(months):
        figures = accrual_totals(months[month], [key])
        trend.append({"month": month.strftime("%Y-%m"), **{field: figures[field] for field in FIELDS}})
    if not profit_visible:
        ever.update(dict.fromkeys(("cogs", "expenses", "stock_corrections", "profit")))
        for point in trend:
            point.update(dict.fromkeys(("cogs", "expenses", "stock_corrections", "profit")))
    since = min((row["date"] for row in rows), default=None)
    return {"key": key, "label": part_names().get(key, key), "since": since, "count": _count(key),
            "all_time": {field: ever[field] for field in FIELDS}, "months": trend,
            "money": part_money(key) if money_visible else None}
