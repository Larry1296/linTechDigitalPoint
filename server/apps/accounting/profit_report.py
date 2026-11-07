"""The one way every profit figure is worked out and explained: the dashboard, the Reports summary, the assistant with or
without an AI model all use it, so the same dates give the same figures everywhere.

Source of truth: the posted books (journal lines) through ``apps.inventory.dashboard.pnl_rows``, never totals worked
out by a screen or by an AI. The accounting basis is accrual for sales, cost of the items sold (each item at the
buying price of the stock it came from, oldest stock first) and running costs, with one adjustment the owner chose:
a sale's profit counts as its money comes in (``credit_profit``). So the profit shown is *profit received*:

    profit received = sales − cost of the items sold − running costs − stock found or missing
                      + interest on investments (after fees) − profit still owed by customers

Money received is cash, never revenue: a customer paying for an older credit sale adds no sale again; it only brings
that sale's profit in (the "profit still owed" line goes below zero for the period it is paid in).

Every report is checked before it is shown (``checks``): the parts add up to the whole, each part's figures give its
profit through the formula, and gross profit is sales less the items' cost. A report that does not add up is logged
for the administrators and returned with ``reconciled: False``; nothing is ever adjusted to make it agree.
"""
import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)
ZERO = Decimal("0")
CENT = Decimal("0.01")
FIELDS = ("revenue", "cogs", "expenses", "stock_corrections", "interest", "owed_profit")
# What the dashboard's "Profit so far" counts: every record, records dated ahead included (commission is dated on its
# month's last day).
ALL_TIME = (date(1900, 1, 1), date(9999, 12, 31))
FORMULA = ("Profit received = sales − cost of the items sold − running costs − stock found or missing + interest on "
           "investments (after fees) − profit still owed by customers")
LABELS = {"revenue": "Sales", "cogs": "Cost of the items sold", "expenses": "Running costs (expenses)",
          "stock_corrections": "Stock found or missing in counts", "interest": "Interest on investments, after fees",
          "owed_profit": "Profit still owed by customers", "gross_profit": "Gross profit (sales less the items' cost)",
          "profit": "Profit received"}
PART_NAMES = {"SHOP": "Shop", "CYBER": "Services", "MPESA": "M-Pesa agency", "INVEST": "Investments"}


def money(value):
    """Shillings and cents, rounded half up: Decimal throughout, never a float."""
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def reconcile_figures(*, revenue, cogs, profit, gross_profit=None, expenses=ZERO, stock_corrections=ZERO, interest=ZERO,
                      owed_profit=ZERO, tolerance=CENT):
    """Problems (empty when it adds up) in a set of profit figures, by the formula above. Used on reports before they
    are shown, and on any breakdown someone (or an AI) gives. ``tolerance`` allows for figures rounded for display."""
    figures = {key: money(value) for key, value in dict(revenue=revenue, cogs=cogs, expenses=expenses, stock_corrections=stock_corrections,
                                                          interest=interest, owed_profit=owed_profit).items()}
    from apps.inventory.dashboard import profit_of
    problems = []
    if gross_profit is not None and abs(money(gross_profit) - (figures["revenue"] - figures["cogs"])) > tolerance:
        problems.append({"check": "gross_profit", "expected": figures["revenue"] - figures["cogs"], "reported": money(gross_profit),
                         "difference": money(gross_profit) - (figures["revenue"] - figures["cogs"]),
                         "explain": "Gross profit is not sales less the cost of the items sold."})
    expected = profit_of(figures)
    if abs(money(profit) - expected) > tolerance:
        problems.append({"check": "profit", "expected": expected, "reported": money(profit), "difference": money(profit) - expected,
                         "explain": "The profit is not what the formula gives from the figures listed: some adjustment is missing "
                                    "from the breakdown, or a figure is wrong."})
    return problems


def _checks(total, parts):
    """Every check of a report: the whole's formula, each part's formula, and the parts adding up to the whole."""
    problems = [{**p, "part": "TOTAL"} for p in reconcile_figures(**{k: total[k] for k in FIELDS}, profit=total["profit"],
                                                                     gross_profit=total["gross_profit"])]
    for key, part in parts.items():
        problems += [{**p, "part": key} for p in reconcile_figures(**{k: part[k] for k in FIELDS}, profit=part["profit"])]
    for field in (*FIELDS, "profit"):
        added = sum((part[field] for part in parts.values()), ZERO)
        if added != total[field]:
            problems.append({"check": f"parts_add_up:{field}", "part": "TOTAL", "expected": total[field], "reported": added,
                             "difference": added - total[field], "explain": f"The parts' {LABELS[field].lower()} do not add up to the whole business's."})
    return problems


def report(start, end, units, label="", rows=None):
    """The profit for ``units`` (the parts the viewer may see; investment interest is added to the whole) from ``start``
    to ``end``: every figure in the formula, each part, where interest, running costs and owed profit came from (down to
    each sale), the formula, and the checks. Runs inside the business's scope."""
    from apps.inventory.dashboard import INVEST, accrual_totals, pnl_rows, whole
    # Rows read once for a wider span may be passed in: every row is dated, so the span's rows are the same either way.
    rows = pnl_rows(start, end) if rows is None else [row for row in rows if start <= row["date"] <= end]
    keys = whole(units, True)
    parts = {key: {k: money(v) for k, v in accrual_totals(rows, [key]).items()} for key in keys}
    parts = {key: part for key, part in parts.items() if key != INVEST or any(part.values())}
    total = {k: money(v) for k, v in accrual_totals(rows, keys).items()}
    total["gross_profit"] = total["revenue"] - total["cogs"]
    detail = {"interest": {}, "expenses": {}, "stock_corrections": {}, "owed_profit": {}}
    for row in rows:
        if row["unit"] in keys and row["field"] in detail:
            name = row.get("sale") or row.get("account") or row["field"]
            entry = detail[row["field"]].setdefault((name, row["unit"]), {"name": name, "part": row["unit"], "amount": ZERO, "dates": set()})
            entry["amount"] += row["amount"]
            entry["dates"].add(row["date"])
    sources = {field: sorted(({"source": e["name"], "part": e["part"], "amount": money(e["amount"]),
                               "from": min(e["dates"]).isoformat(), "to": max(e["dates"]).isoformat()} for e in entries.values() if e["amount"]),
                             key=lambda e: -abs(e["amount"]))[:25]
               for field, entries in detail.items()}
    problems = _checks(total, parts)
    if problems:
        from apps.tenancy.context import organization_id
        logger.error("Profit report does not add up (organization %s, %s to %s): %s", organization_id(), start, end,
                     "; ".join(f"{p['part']} {p['check']} off by {p['difference']}" for p in problems))
    dates = sorted(row["date"] for row in rows)
    return {"label": label, "start": start, "end": end, "basis": "accrual books, each sale's profit counted as it is paid",
            "formula": FORMULA, "total": total, "parts": parts, "sources": sources,
            "records": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None, "lines": len(rows)},
            "reconciled": not problems, "checks": problems}


def _month(day, offset=0):
    index = day.year * 12 + day.month - 1 + offset
    return day.replace(year=index // 12, month=index % 12 + 1, day=1)


def dashboard_figures(units):
    """Each profit the dashboard can show, as (key, label, start, end, part or None): the headline since the start and
    each part's, the date-range section (this month by default), today and last month."""
    today = timezone.localdate()
    month = today.replace(day=1)
    last_end = month - timedelta(days=1)
    figures = [("all_time", "Profit so far, every part together (dashboard headline)", *ALL_TIME, None)]
    figures += [(f"all_time:{key}", f"{PART_NAMES.get(key, key)} profit since the start", *ALL_TIME, key) for key in units]
    figures += [("this_month", f"Profit received this month ({month:%d %b} to {today:%d %b}), the dashboard's date range", month, today, None),
                ("today", f"Profit received today ({today:%d %b})", today, today, None),
                ("last_month", f"Profit received last month ({_month(last_end):%B %Y})", _month(last_end), last_end, None)]
    figures += [(f"this_month:{key}", f"{PART_NAMES.get(key, key)} profit this month", month, today, key) for key in units]
    return figures


def find_figure(amount, units, extra=()):
    """Which profit the business sees that ``amount`` is (to the shilling, as people read it off the screen), with its
    full report; or None and the nearest figures. Never picks a different figure: no match is said as no match."""
    from apps.inventory.dashboard import pnl_rows
    amount = money(amount)
    reports, nearest = {}, []
    every = pnl_rows(*ALL_TIME)
    for key, label, start, end, part in [*extra, *dashboard_figures(units)]:
        span = (start, end)
        if span not in reports:
            reports[span] = report(start, end, units, label, rows=every)
        found = reports[span]
        value = found["total"]["profit"] if part is None else found["parts"].get(part, {}).get("profit")
        if value is None:
            continue
        if abs(value - amount) < 1:
            if part is not None:
                found = {**found, "label": label, "only_part": part}
            return {"matched": True, "figure": key, "label": label, "value": value, "report": {**found, "label": label}}, None
        nearest.append({"figure": key, "label": label, "value": value, "difference": value - amount})
    nearest.sort(key=lambda row: abs(row["difference"]))
    return None, nearest[:4]
