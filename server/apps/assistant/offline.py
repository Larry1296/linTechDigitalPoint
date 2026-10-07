"""Answers without an AI model: when no AI key is set, or the AI service fails, the business assistant still answers
the common questions from the same read-only tools, with exact figures, in plain words.

It recognises what is asked (sales trend, profit and loss, stock to reorder, who owes, ...) and the period
("this month", "last 30 days", "since we started"), runs the matching tool for the person asking (so their role's
limits still apply) and writes the result out. Anything it does not recognise is looked up in the help articles.
"""
import calendar
import json
import re
from datetime import timedelta

from django.utils import timezone

from . import business_tools

NOTE = "\n\n_(Answered directly from your records. The AI assistant is not connected, so only common questions are understood.)_"


# Periods ---------------------------------------------------------------------------------------

def _month_bounds(day):
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def period(text, default_days=30):
    """(start, end, words) for the period the question names, else the last ``default_days`` days."""
    today = timezone.localdate()
    if re.search(r"\b(since (we|i|the business) (started|began|opened)|all[- ]time|ever|from the (start|beginning))\b", text):
        return "beginning", today, "since the business started"
    if "yesterday" in text:
        day = today - timedelta(days=1)
        return day, day, f"yesterday ({day:%d %b})"
    if "today" in text:
        return today, today, f"today ({today:%d %b})"
    if "last week" in text:
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6), f"last week ({start:%d %b} to {start + timedelta(days=6):%d %b})"
    if "this week" in text:
        start = today - timedelta(days=today.weekday())
        return start, today, f"this week ({start:%d %b} to {today:%d %b})"
    if "last month" in text:
        start, end = _month_bounds(today.replace(day=1) - timedelta(days=1))
        return start, end, f"last month ({start:%B %Y})"
    if "this month" in text or "month to date" in text:
        start = today.replace(day=1)
        return start, today, f"this month ({start:%d %b} to {today:%d %b})"
    if "this year" in text:
        start = today.replace(month=1, day=1)
        return start, today, f"this year ({start:%d %b %Y} to {today:%d %b})"
    match = re.search(r"\b(?:last|past|previous)\s+(\d{1,4})\s*(day|week|month)s?\b", text)
    if match:
        days = int(match.group(1)) * {"day": 1, "week": 7, "month": 30}[match.group(2)]
        days = max(1, min(days, business_tools.MAX_DAYS))
        start = today - timedelta(days=days - 1)
        return start, today, f"the last {days} days ({start:%d %b} to {today:%d %b})"
    start = today - timedelta(days=default_days - 1)
    return start, today, f"the last {default_days} days ({start:%d %b} to {today:%d %b})"


def _days(text, default):
    match = re.search(r"\b(\d{1,4})\s*days?\b", text)
    return int(match.group(1)) if match else default


# Formatting ------------------------------------------------------------------------------------

class Writer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.currency = ctx.organization.currency or ""
        self.used = []

    def money(self, value):
        number = float(value or 0)
        sign = "-" if number < 0 else ""
        return f"{sign}{self.currency} {abs(number):,.0f}" if abs(number) >= 100 or number == int(number) else f"{sign}{self.currency} {abs(number):,.2f}"

    def call(self, name, args=None):
        """The tool's result, or None (with the reason in ``self.problem``) when this person cannot use it."""
        offered = {n for n, _, _ in business_tools.available(self.ctx)}
        if name not in offered:
            self.problem = "Your role does not include this information. The owner or a manager can give you access."
            return None
        self.used.append(name)
        text, failed = business_tools.run(self.ctx, name, args or {})
        if failed:
            try:
                self.problem = json.loads(text).get("error") or "That lookup failed."
            except ValueError:
                self.problem = "That lookup failed."
            return None
        return json.loads(text)


def _args(start, end):
    return {"start_date": start if start == "beginning" else start.isoformat(), "end_date": end.isoformat()}


def _span(data):
    p = data.get("period") or {}
    return f"{p.get('start')} to {p.get('end')}" if p else ""


# Answers ---------------------------------------------------------------------------------------

def sales_trend(w, text):
    start, end, words = period(text, 90)
    data = w.call("sales_statistics", {**_args(start, end), "forecast_days": 7})
    if data is None:
        return w.problem
    s = data["statistics"]
    if not s.get("days") or not s.get("total"):
        return f"There are no completed sales in {words}, so there is no trend yet."
    t = s["trend"]
    if t["strength"] == "too few days to tell":
        lines = [f"**Too early to call a trend:** there are only {s['days']} days of records ({_span(data)}). "
                 f"Here is what they show so far.", ""]
    else:
        lines = []
    lines += [] if lines else [f"**Sales {('are ' + t['direction']) if t['direction'] != 'flat' else 'are flat'}** over {_span(data)} "
             f"({s['days']} days), but the trend is **{t['strength']}** (R² {t['r_squared']}), so treat it with care."
             if t["strength"] != "strong" else f"**Sales are clearly {t['direction']}** over {_span(data)} ({s['days']} days, R² {t['r_squared']}).", ""]
    lines += [f"- Total sales: **{w.money(s['total'])}**",
              f"- Average per day: {w.money(s['mean_per_day'])} (median {w.money(s['median_per_day'])})",
              *([f"- Trend: about {w.money(abs(t['slope_per_day']))} a day {'more' if t['slope_per_day'] >= 0 else 'less'} each day"]
                if t["strength"] != "too few days to tell" else []),
              f"- Days with no sales: {s['days_without_activity']} of {s['days']}"]
    if data.get("records_start"):
        lines.append(f"- Your records start on {data['records_start']}, so the period begins there.")
    if data.get("change_vs_previous_period_pct") is not None:
        lines.append(f"- Compared with the same length of time before: {data['change_vs_previous_period_pct']:+.1f}%")
    best = sorted(((v, d) for d, v in (s.get("average_by_weekday") or {}).items() if v), reverse=True)
    if best:
        lines.append(f"- Best weekday on average: {best[0][1]} ({w.money(best[0][0])})")
    for day in (s.get("unusual_days") or [])[:3]:
        lines.append(f"- {day['date']} was {day['kind']}: {w.money(day['value'])}")
    if 14 <= s["days"] < 28:
        lines += ["", "With under four weeks of sales the trend is not reliable yet; it will firm up as more days are recorded."]
    return "\n".join(lines)


def profit_and_loss(w, text):
    start, end, words = period(text + (" this month" if not re.search(r"day|week|month|year|today|yesterday|since|ever", text) else ""))
    data = w.call("financial_summary", _args(start, end))
    if data is None:
        return w.problem
    t = data["totals"]
    net = float(t["net_profit"])
    lines = [f"**{'Profit' if net >= 0 else 'Loss'} of {w.money(abs(net))}** for {words}, from the posted books (accrual basis).", "",
             f"- Revenue: **{w.money(t['revenue'])}**", f"- Cost of goods sold: {w.money(t['cogs'])}",
             f"- Gross profit: {w.money(t['gross_profit'])}" + (f" ({float(t['gross_profit']) / float(t['revenue']) * 100:.1f}% margin)" if float(t["revenue"]) else ""),
             f"- Running costs (expenses): {w.money(t['expenses'])}"]
    if float(t.get("stock_corrections") or 0):
        lines.append(f"- Stock corrections: {w.money(t['stock_corrections'])}")
    lines.append(f"- Net profit: **{w.money(t['net_profit'])}**")
    lines.append(f"- Money actually received: {w.money(t['money_received'])} (not the same as revenue: credit sales are not yet paid)")
    units = [u for u in data.get("units", []) if float(u["revenue"]) or float(u["expenses"])]
    if len(units) > 1:
        lines += ["", "By part of the business:"]
        lines += [f"- {u['business_unit'].title()}: revenue {w.money(u['revenue'])}, net {w.money(u['net_profit'])}" for u in units]
    return "\n".join(lines)


def reorder(w, text):
    data = w.call("stock_levels", {"view": "low", "limit": 15})
    if data is None:
        return w.problem
    s = data["summary"]
    if not data["items"]:
        return f"Nothing is running low: none of your {s['stock_items']} stock items is at or below its minimum."
    lines = [f"**{s['out_of_stock']} out of stock and {s['low_stock']} running low** (of {s['stock_items']} stock items).", ""]
    for item in data["items"]:
        reorder_qty = f", reorder about **{item['suggested_reorder']:g}**" if item.get("suggested_reorder") else ""
        lines.append(f"- {item['product']}: {item['available']:g} available (minimum {item['minimum_stock']:g}){reorder_qty}")
    lines += ["", "Suggested quantities bring each item back up to its target stock. Items without a target show none."]
    return "\n".join(lines)


def dead_stock(w, text):
    days = _days(text, 60)
    data = w.call("inventory_analysis", {"days": days, "limit": 20})
    if data is None:
        return w.problem
    dead = data["dead_stock_no_sales_in_period"]
    if not dead:
        return f"Every stock item with units on hand sold at least once in the last {days} days."
    lines = [f"**{data['dead_stock_count']} items have stock but no sales** in the last {days} days"
             + (f", holding **{w.money(data['dead_stock_value_at_cost'])}** at cost." if data.get("dead_stock_value_at_cost") is not None else "."), ""]
    lines += [f"- {row['product']}: {row['on_hand']:g} on hand" + (f" ({w.money(row['stock_value_at_cost'])} at cost)" if row.get("stock_value_at_cost") is not None else "")
              for row in dead]
    if data.get("records_start"):
        lines += ["", f"Your records start on {data['records_start']}, so items may simply not have had time to sell."]
    return "\n".join(lines)


def top_products(w, text):
    start, end, words = period(text, 90)
    data = w.call("sales_summary", {**_args(start, end), "group_by": "product", "limit": 10})
    if data is None:
        return w.problem
    rows = data["rows"]
    if not rows:
        return f"No products were sold in {words}."
    total = sum(r["value"] or 0 for r in data["rows"]) or 1
    lines = [f"**{rows[0]['product']}** brought in the most in {words}: {w.money(rows[0]['value'])} "
             f"({(rows[0]['value'] or 0) / total * 100:.0f}% of product sales).", ""]
    for row in rows:
        profit = f", gross profit {w.money(row['gross_profit'])}" if row.get("gross_profit") is not None else ""
        lines.append(f"- {row['product']}: {w.money(row['value'])} from {row['units_sold']:g} sold{profit}")
    return "\n".join(lines)


def busiest(w, text):
    start, end, words = period(text, 90)
    days = w.call("sales_summary", {**_args(start, end), "group_by": "weekday", "limit": 7})
    if days is None:
        return w.problem
    if not days["rows"]:
        return f"There are no completed sales in {words} to compare days and hours."
    hours = w.call("sales_summary", {**_args(start, end), "group_by": "hour", "limit": 24}) or {"rows": []}
    top_hours = sorted(hours["rows"], key=lambda r: r["sales"], reverse=True)[:3]
    lines = [f"**Busiest day: {days['rows'][0]['weekday']}** ({days['rows'][0]['sales']} sales, {w.money(days['rows'][0]['value'])}) in {words}.", "", "By weekday:"]
    lines += [f"- {r['weekday']}: {r['sales']} sales, {w.money(r['value'])}" for r in days["rows"]]
    if top_hours:
        lines += ["", "Busiest hours: " + ", ".join(f"{r['hour']} ({r['sales']} sale{'s' if r['sales'] != 1 else ''})" for r in top_hours)]
    if days["period"]["days"] < 28:
        lines += ["", "Each weekday has only happened a few times so far, so this pattern may change."]
    return "\n".join(lines)


def sales(w, text):
    start, end, words = period(text + (" today" if not re.search(r"day|week|month|year|since|ever", text) else ""))
    data = w.call("sales_summary", {**_args(start, end), "group_by": "payment_method"})
    if data is None:
        return w.problem
    t = data["totals"]
    if not t["sales_count"]:
        return f"No completed sales {words}."
    lines = [f"**{t['sales_count']} sale{'s' if t['sales_count'] != 1 else ''} worth {w.money(t['sales_value'])}** {words}.", "",
             f"- Average sale: {w.money(t['average_sale'])}", f"- Discounts given: {w.money(t['discounts_given'])}"]
    if t.get("gross_profit") is not None:
        lines.append(f"- Gross profit: {w.money(t['gross_profit'])} ({t['gross_margin_pct']}% margin)")
    if data["rows"]:
        lines.append("- Paid by: " + ", ".join(f"{r['payment_method'].title()} {w.money(r['value'])}" for r in data["rows"]))
    unpaid = (t["sales_value"] or 0) - sum(r["value"] or 0 for r in data["rows"])
    if unpaid > 0.5:
        lines.append(f"- Not paid yet (on credit): {w.money(unpaid)}")
    return "\n".join(lines)


def owed_to_me(w, text):
    data = w.call("money_owed_to_business", {"limit": 15})
    if data is None:
        return w.problem
    lines = [f"**Customers owe you {w.money(data['customers_owe_total'])}** ({data['customers_owing']} customer{'s' if data['customers_owing'] != 1 else ''})."]
    if data["customers"]:
        lines += [""] + [f"- {c['customer']}: {w.money(c['owed'])} from {c['unpaid_sales']} sale{'s' if c['unpaid_sales'] != 1 else ''} since {c['oldest_unpaid_sale']}"
                         + (f", {w.money(c['overdue'])} overdue" if c["overdue"] else "") for c in data["customers"]]
    if data.get("by_age"):
        lines += ["", "By age: " + ", ".join(f"{k} {w.money(v)}" for k, v in data["by_age"].items())]
    lent = data.get("money_lent_out")
    if lent and lent["loans"]:
        lines += ["", f"**Money lent out still owed: {w.money(lent['total_still_owed'])}**"]
        lines += [f"- {l['borrower']}: {w.money(l['still_owed'])} ({l['status'].replace('_', ' ').lower()}, due {l['due']})" for l in lent["loans"]]
    if data.get("refunds_the_business_owes_customers"):
        lines += ["", f"You owe customers {w.money(data['refunds_the_business_owes_customers'])} in refunds."]
    return "\n".join(lines)


def i_owe(w, text):
    data = w.call("money_business_owes", {"limit": 15})
    if data is None:
        return w.problem
    total = float(data["suppliers_total"] or 0) + float(data["unpaid_bills_total"] or 0)
    if not total:
        return "You owe nothing right now: no unpaid supplier purchases and no unpaid bills."
    lines = [f"**You owe {w.money(total)}**: suppliers {w.money(data['suppliers_total'])}, unpaid bills {w.money(data['unpaid_bills_total'])}.", ""]
    lines += [f"- {s['supplier']}: {w.money(s['owed'])} ({s['unpaid_purchases']} purchase(s), oldest {s['oldest']})" for s in data["suppliers"]]
    lines += [f"- {b['bill']}{' — ' + b['description'] if b['description'] else ''}: {w.money(b['owed'])}" + (" **overdue**" if b["overdue"] else "")
              for b in data["unpaid_bills"]]
    return "\n".join(lines)


def money_position(w, text):
    data = w.call("money_position")
    if data is None:
        return w.problem
    lines = [f"**Net worth: {w.money(data['net_worth'])}**: the business owns {w.money(data['owns'])} and owes {w.money(data['owes'])}.", ""]
    for group in data["groups"]:
        if group["amount"]:
            lines.append(f"- {group['label']}: {w.money(group['amount'])}")
            for item in group.get("items") or []:
                if item.get("amount"):
                    lines.append(f"  - {item['label']}: {w.money(item['amount'])}")
    if data.get("left_out"):
        lines += ["", "Not included (your role cannot see it): " + ", ".join(data["left_out"])]
    return "\n".join(lines)


def expenses(w, text):
    start, end, words = period(text + (" this month" if not re.search(r"day|week|month|year|since|ever", text) else ""))
    data = w.call("expense_analysis", _args(start, end))
    if data is None:
        return w.problem
    if not data["total_expenses"]:
        return f"No running costs were recorded for {words}."
    lines = [f"**Running costs: {w.money(data['total_expenses'])}** for {words}"
             + (f", {data['expenses_as_pct_of_revenue']}% of revenue." if data.get("expenses_as_pct_of_revenue") is not None else "."), ""]
    lines += [f"- {row['category']}: {w.money(row['amount'])} ({row['share_pct']}%)" for row in data["by_category"][:10]]
    return "\n".join(lines)


def agency(w, text):
    data = w.call("agency_commission", {"months": 6})
    if data is None:
        return w.problem
    lines = []
    for outlet in data["money_in_operation"]:
        if outlet.get("total") is not None:
            lines.append(f"- {outlet['outlet']}: cash {w.money(outlet['cash'])}, float {w.money(outlet['float'])} "
                         f"(total {w.money(outlet['total'])}, as of {outlet['updated_on']})")
    head = ["**M-Pesa agency money in operation:**"] + (lines or ["- No shift recorded yet."])
    months = [m for m in data["months"] if m["commission_earned"] or m["agency_running_costs"]]
    head += ["", "**Commission by month:**"] + ([f"- {m['month']}: commission {w.money(m['commission_earned'])}, costs {w.money(m['agency_running_costs'])}, "
                                                f"profit {w.money(m['profit'])}" for m in months] or ["- No commission recorded in the last 6 months."])
    if data.get("commission_not_yet_recorded_for"):
        head += ["", f"{data['commission_not_yet_recorded_for']}'s commission is not recorded yet."]
    return "\n".join(head)


def stock_value(w, text):
    data = w.call("stock_levels", {"view": "all", "limit": 1})
    if data is None:
        return w.problem
    s = data["summary"]
    value = f", worth **{w.money(s['stock_value_at_cost'])}** at cost" if s.get("stock_value_at_cost") is not None else ""
    return (f"You have **{s['units_on_hand']:g} units** across {s['stock_items']} stock items{value}. "
            f"{s['out_of_stock']} are out of stock and {s['low_stock']} are running low.")


def customers(w, text):
    start, end, words = period(text, 90)
    data = w.call("top_customers", {**_args(start, end), "limit": 10})
    if data is None:
        return w.problem
    lines = [f"**{data['named_customers']} named customers** bought in {words} ({data['new_customers']} new, {data['returning_customers']} returning), "
             f"plus {data['walk_in_sales']} walk-in sales worth {w.money(data['walk_in_value'])}."]
    if data["customers"]:
        lines += ["", "Top customers:"] + [f"- {c['customer']}: {w.money(c['spent'])} over {c['sales']} sale(s)" for c in data["customers"]]
    return "\n".join(lines)


def help_answer(w, text):
    from .retrieval import tokens
    data = w.call("platform_help", {"question": text})
    if not data or not data["passages"]:
        return None
    top = data["passages"][0]
    # Only a real match: most of the question's words must appear in the article (no answer beats a wrong one).
    asked = set(tokens(text)) - {"tell", "know", "want", "need", "please", "thank", "thanks", "hello", "hi"}
    found = set(tokens(f"{top['section']} {top['text']}"))
    if not asked or len(asked & found) * 2 < len(asked):
        return None
    return f"**{top['section']}**\n\n{top['text']}"


FALLBACK = ("I can answer these without the AI assistant: sales today, this week or this month; how sales are trending; profit and "
            "loss; busiest days and hours; top products; what is running low; stock that has not sold; stock value; who owes you; "
            "what you owe; where your money is (net worth); expenses; top customers; M-Pesa agency and commission; and how to do "
            "something in the app. Try asking one of those.")

# (pattern, answer). The first match wins, so the more specific questions come first.
INTENTS = [
    (r"^(how (do|can|should) i|how to|where (do|can) i|can i|is it possible|what is the way)\b", help_answer),
    (r"\b(trend|trending|forecast|grow|growing|growth|predict|going up|going down|declin)", sales_trend),
    (r"\b(busiest|busy|peak|quiet|which day|what day|best day|hours?)\b", busiest),
    (r"\b(profit|loss|p&l|p ?and ?l|income statement|margin|net income|making money)\b", profit_and_loss),
    (r"\b(not sold|haven'?t sold|has not sold|hasn'?t sold|dead stock|slow[- ]moving|not selling|unsold)\b", dead_stock),
    (r"\b(running low|low stock|reorder|re-order|restock|out of stock|running out|need to buy|order more)\b", reorder),
    (r"\b(owes? me|owe us|who owes|debtors?|credit sales|unpaid sales|receivables?|lent|loans?)\b", owed_to_me),
    (r"\b(i owe|we owe|do i owe|suppliers?|payables?|bills?|creditors?)\b", i_owe),
    (r"\b(net worth|worth|where is (my|the) money|how much money|cash|bank|balances?|assets?)\b", money_position),
    (r"\b(expenses?|spent|spending|running costs?|costs?)\b", expenses),
    (r"\b(commission|m-?pesa|float|agency|agent)\b", agency),
    (r"\b(top|best[- ]selling|best sellers?|most (revenue|sales|money)|bring in|popular)\b.*\b(products?|items?|sellers?|revenue)?", top_products),
    (r"\b(customers?|clients?|buyers?)\b", customers),
    (r"\b(stock value|value of (my )?stock|how much stock|stock on hand|inventory)\b", stock_value),
    (r"\b(sales|sold|revenue|turnover|sell|takings)\b", sales),
]


def answer(ctx, question):
    """(markdown answer, tools used). Runs inside the business's scope."""
    text = " ".join(question.lower().split())
    w = Writer(ctx)
    for pattern, handler in INTENTS:
        if re.search(pattern, text):
            result = handler(w, text)
            if result:
                return result + NOTE, w.used
    found = help_answer(w, text)
    return (found + NOTE if found else FALLBACK), w.used
