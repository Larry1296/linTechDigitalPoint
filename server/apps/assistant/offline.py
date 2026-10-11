"""Answers without an AI model: when no AI key is set, or the AI service fails (no credit, an outage), the business
assistant still answers the common questions from the same read-only tools, with exact figures, in plain words. A
business is never told the AI was unavailable: it simply gets its answer (business_chat.unavailable_reason).

It recognises what is asked (sales trend, profit and loss, stock to reorder, who owes, ...) and the period
("this month", "last 30 days", "since we started"), runs the matching tool for the person asking (so their role's
limits still apply) and writes the result out. Anything it does not recognise is looked up in the help articles.
"""
import calendar
import difflib
import json
import re
from datetime import timedelta

from django.utils import timezone

from . import business_tools

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


def table(head, rows):
    """A Markdown table: the chat shows it as a real table."""
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(cell).replace("|", "/") for cell in row) + " |" for row in rows]
    return out


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
    lines += ["### The figures", f"- Total sales: **{w.money(s['total'])}**",
              f"- Average per day: {w.money(s['mean_per_day'])} (median {w.money(s['median_per_day'])})",
              *([f"- Trend: about {w.money(abs(t['slope_per_day']))} a day {'more' if t['slope_per_day'] >= 0 else 'less'} each day"]
                if t["strength"] != "too few days to tell" else []),
              f"- Days with no sales: {s['days_without_activity']} of {s['days']}"]
    if data.get("change_vs_previous_period_pct") is not None:
        lines.append(f"- Compared with the same length of time before: {data['change_vs_previous_period_pct']:+.1f}%")
    best = sorted(((v, d) for d, v in (s.get("average_by_weekday") or {}).items() if v), reverse=True)
    if best:
        lines.append(f"- Best weekday on average: {best[0][1]} ({w.money(best[0][0])})")
    for day in (s.get("unusual_days") or [])[:3]:
        lines.append(f"- {day['date']} was {day['kind']}: {w.money(day['value'])}")
    if data.get("records_start"):
        lines += ["", f"> Your records start on {data['records_start']}, so the period begins there."]
    if 14 <= s["days"] < 28:
        lines += ["", "> With under four weeks of sales the trend is not reliable yet; it will firm up as more days are recorded."]
    return "\n".join(lines)


def profit_and_loss(w, text):
    start, end, words = period(text + (" this month" if not re.search(r"day|week|month|year|today|yesterday|since|ever", text) else ""))
    data = w.call("financial_summary", _args(start, end))
    if data is None:
        return w.problem
    t = data["totals"]
    net = float(t["net_profit"])
    lines = [f"**{'Profit' if net >= 0 else 'Loss'} of {w.money(abs(net))}** for {words}, from the posted books (accrual basis).", "",
             "### The figures", f"- Revenue: **{w.money(t['revenue'])}**", f"- Cost of goods sold: {w.money(t['cogs'])}",
             f"- Gross profit: {w.money(t['gross_profit'])}" + (f" ({float(t['gross_profit']) / float(t['revenue']) * 100:.1f}% margin)" if float(t["revenue"]) else ""),
             f"- Running costs (expenses): {w.money(t['expenses'])}"]
    if float(t.get("stock_corrections") or 0):
        lines.append(f"- Stock corrections: {w.money(t['stock_corrections'])}")
    lines.append(f"- Net profit: **{w.money(t['net_profit'])}**")
    units = [u for u in data.get("units", []) if float(u["revenue"]) or float(u["expenses"])]
    if len(units) > 1:
        lines += ["", "### By business unit"]
        lines += table(["Unit", "Revenue", "Costs", "Net"], [[u["business_unit"].title(), w.money(u["revenue"]),
                                                             w.money(float(u["cogs"]) + float(u["expenses"])), w.money(u["net_profit"])] for u in units])
    received, revenue = float(t["money_received"]), float(t["revenue"])
    if abs(received - revenue) > 0.5:
        lines += ["", f"> Money actually received is {w.money(received)}. Revenue counts sales when made, so credit sales not yet "
                      "paid are in revenue but not in the money received."]
    if not float(t["expenses"]):
        lines += ["", "> No running costs (rent, power, wages) are recorded for this period, so the real profit is lower."]
    return "\n".join(lines)


def _category_named(text):
    """A category from the catalogue named in the question ("which remotes are low" -> REMOTES), else ""."""
    from apps.catalog.models import Category
    words = set(re.findall(r"[a-z0-9]+", text))
    for name in sorted(Category.objects.values_list("name", flat=True), key=len, reverse=True):
        key = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
        if key and all(k in words or k.rstrip("s") in words or k + "s" in words for k in key):
            return name
    return ""


def reorder(w, text):
    category = _category_named(text)
    data = w.call("stock_levels", {"view": "low", "limit": 15, **({"category": category} if category else {})})
    if data is None:
        return w.problem
    s = data["summary"]
    if not data["items"]:
        return f"Nothing is running low{' in ' + category if category else ''}: none of your {s['stock_items']} stock items is at or below its minimum."
    lines = [f"**{s['out_of_stock']} out of stock and {s['low_stock']} running low** (of {s['stock_items']} stock items"
             f"{' in ' + category if category else ''}).", ""]
    lines += table(["Product", "Left", "Min", "Reorder"], [[item["product"], "**0**" if item["available"] <= 0 else f"{item['available']:g}",
                                                           f"{item['minimum_stock']:g}", f"{item['suggested_reorder']:g}" if item.get("suggested_reorder") else "—"]
                                                          for item in data["items"]])
    lines += ["", "> Reorder quantities bring each item back up to its target stock; items without a target show —."]
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
    words = words if words.startswith(("today", "yesterday", "this", "last", "since")) else "in " + words
    if not rows:
        return f"No products were sold {words}."
    total = sum(r["value"] or 0 for r in data["rows"]) or 1
    lines = [f"**{rows[0]['product']}** brought in the most {words}: {w.money(rows[0]['value'])} "
             f"({(rows[0]['value'] or 0) / total * 100:.0f}% of product sales).", ""]
    profit = rows[0].get("gross_profit") is not None
    lines += table(["Product", "Sold", "Revenue"] + (["Profit"] if profit else []),
                   [[r["product"], f"{r['units_sold']:g}", w.money(r["value"])] + ([w.money(r["gross_profit"])] if profit else []) for r in rows])
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
    lines = [f"**Net worth: {w.money(data['net_worth'])}**: the business owns {w.money(data['owns'])} and owes {w.money(data['owes'])}."]
    for side, title in [("OWNS", "What you own"), ("OWES", "What you owe")]:
        groups = [g for g in data["groups"] if g.get("side") == side and g["amount"]]
        if groups:
            lines += ["", f"### {title}"]
        for group in groups:
            lines.append(f"- {group['label']}: **{w.money(group['amount'])}**")
            for item in group.get("items") or []:
                if item.get("amount"):
                    lines.append(f"  - {item['label']}: {w.money(item['amount'])}")
    if not any(g.get("side") == "OWES" and g["amount"] for g in data["groups"]):
        lines += ["", "### What you owe", "- Nothing right now."]
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
    return "\n".join(head)


def _phone(number):
    return "0" + number[3:] if number and number.startswith("254") else (number or "")


def mpesa_shift(w, text):
    start, end, words = period(text, 1)
    data = w.call("mpesa_summary", {**_args(start, end), "limit": 10})
    if data is None:
        return w.problem
    shift = next((s for s in data["shifts"] if s["status"] == "OPEN"), None)
    if shift:
        tx = shift["transactions"]
        lines = [f"**Open shift** at {shift['outlet']}, opened {shift['opened']} by {shift['operator']}: "
                 f"cash **{w.money(shift['cash_now'])}**, float **{w.money(shift['float_now'])}** now "
                 f"(opened with {w.money(shift['opening_cash'])} cash and {w.money(shift['opening_float'])} float)."]
        totals = shift["transactions_by_type"]
    else:
        tx = data["latest_transactions"]
        lines = [f"No M-Pesa shift is open. **{data['transactions']} transactions** in {words}."]
        totals = data["transactions_by_type"]
    if totals:
        lines += ["", "### By type", *table(["Type", "Count", "Amount"],
                                            [[t["type"].replace("_", " ").title(), t["count"], w.money(t["amount"])] for t in totals])]
    if tx:
        lines += ["", "### Latest", *table(["Time", "Type", "Amount", "Customer"],
                                          [[t["when"][11:], t["type"].replace("_", " ").title() + (" (reversed)" if t["reversed"] else ""),
                                            w.money(t["amount"]), " ".join(x for x in (t["customer"], _phone(t["phone"])) if x) or "-"] for t in tx])]
    return "\n".join(lines)


def stock_value(w, text):
    data = w.call("stock_levels", {"view": "all", "limit": 1})
    if data is None:
        return w.problem
    s = data["summary"]
    value = f", worth **{w.money(s['stock_value_at_cost'])}** at cost" if s.get("stock_value_at_cost") is not None else ""
    return (f"You have **{s['units_on_hand']:g} units** across {s['stock_items']} stock items{value}. "
            f"{s['out_of_stock']} {'is' if s['out_of_stock'] == 1 else 'are'} out of stock and {s['low_stock']} "
            f"{'is' if s['low_stock'] == 1 else 'are'} running low.")


def stock_list(w, text):
    """What is in stock, grouped by category and subcategory, items in alphabetical order within each."""
    category = ""
    # The last "in/under/from X" names the category: "which items are in stock in cables" -> cables.
    match = re.search(r".*\b(?:in|under|from) (?:the )?(?:category )?([a-z0-9 &()-]+?)(?: category)?[?.!]*$", text)
    # A category name is a few words; a longer tail is the rest of a sentence ("in nairobi if you notice …"), not a category.
    if match and match.group(1).strip() not in {"stock", "my stock", "the shop", "store", "shop", "the store"} and len(match.group(1).split()) <= 4:
        category = match.group(1).strip()
    data = w.call("stock_levels", {"view": "all", "limit": 200, **({"category": category} if category else {})})
    if data is None:
        return w.problem
    s = data["summary"]
    have = [i for i in data["items"] if (i["available"] or 0) > 0]
    where = f" in {category}" if category else ""
    if not data["items"]:
        return f"No stock items found{where}. Check the category name on the Categories page."
    if not have:
        return f"Nothing is in stock{where} right now ({s['stock_items']} stock items, all at zero)."
    value = f", worth {w.money(s['stock_value_at_cost'])} at cost" if s.get("stock_value_at_cost") is not None else ""
    lines = [f"**{len(have)} of {s['stock_items']} item{'s are' if s['stock_items'] != 1 else ' is'} in stock**{where} ({s['units_on_hand']:g} units{value}), by category:"]
    groups = {}
    for item in have:
        path = (item.get("category_path") or item["category"]).split(" › ")
        groups.setdefault(path[0], {}).setdefault(" › ".join(path[1:]), []).append(item)
    for top in sorted(groups, key=str.lower):
        count = sum(len(items) for items in groups[top].values())
        lines += ["", f"### {top} ({count})"]
        for sub in sorted(groups[top], key=lambda name: (name != "", name.lower())):  # items directly in the category first
            if sub:
                lines += [f"**{sub}**"]
            for item in sorted(groups[top][sub], key=lambda i: i["product"].lower()):
                low = " (low)" if item["minimum_stock"] and item["available"] <= item["minimum_stock"] else ""
                lines.append(f"- {item['product']}: {item['available']:g} available{low}")
    out = sorted(i["product"] for i in data["items"] if (i["available"] or 0) <= 0)
    if out:
        lines += ["", f"> **Out of stock:** {', '.join(out[:15])}{' …' if len(out) > 15 else ''}"]
    return "\n".join(lines)


# The lowest price a sale can be made at: "lowest price a customer can pay for the MP charger".
LOWEST = r"\b(?:lowest|least|minimum|min|cheapest|bottom|floor)\b"
# A price offered for a product: "can a customer pay 600 for the MP charger", "can I sell the MP charger at 650".
OFFER = r"\b(?:pay|sell|give|accept|take|charge)\b.*?\b(?:kes|ksh|sh)?\s*(\d[\d,]*)\b"
PRODUCT_QUESTIONS = [OFFER + r"\s*(?:for|of) (?:the |a |an |my )?(.+)$", LOWEST + r".*\b(?:for|of|on)\s+(.+)$", r".*\bprices? (?:for|of) (.+)$",
                     LOWEST + r".*\b(?:sell|pay|charge|price)\b\s+(?:the |a |an |my )?(.+)$",
                     r"\bsell (?:the |a |an |my )?(.+?) (?:for|at)\b",
                     r"\bdo (?:i|we) (?:have|stock|sell) (?:any )?(.+?)(?: in stock| left| available)?$",
                     r"\bhow many (.+?) (?:do (?:i|we) have|are (?:left|there|in stock|available)|left|in stock)$",
                     r"\bis (?:there )?(?:any )?(.+?) (?:in stock|available|left)$", r"\bare (?:there )?(?:any )?(.+?) (?:in stock|available|left)$",
                     r"\b(?:price|cost|selling price) of (?:the |a |an )?(.+)$", r"\bhow much (?:is|does|do) (?:the |a |an )?(.+?)(?: cost| sell for| go for)?$",
                     r"\b(?:find|look up|search for|check) (?:the )?(?:product )?(.+)$"]


def product_name(text):
    clean = text.rstrip(" ?.!")
    for pattern in PRODUCT_QUESTIONS:
        match = re.search(pattern, clean)
        if match:
            name = re.sub(r"^(?:the|a|an|any|some|my) ", "", match.group(match.lastindex).strip())
            name = re.sub(r"^(?:the|a|an|any|some|my|each|one) ", "", name)
            if name and name not in {"stock", "item", "items", "product", "products", "money", "it", "that", "this", "everything", "all"}:
                return name
    return None


def _word_score(word, tokens):
    """How well one word asked matches a product's words: 1 for the word itself (or the start of one, "charg"), else how
    close the nearest is ("chager" ~ "charger"). Two-letter words ("mp", a brand) must match exactly."""
    if word in tokens or (len(word) > 2 and any(t.startswith(word) for t in tokens)):
        return 1.0
    if len(word) <= 2:
        return 0.0
    return max((difflib.SequenceMatcher(None, word, t).ratio() for t in tokens), default=0.0)


def closest_products(name, limit=10):
    """SKUs of the products a loosely typed name means, best first: every word asked is matched against the product's
    name, variant, brand, item code and category, so "mp chager" finds MULTIPLE POWER CHARGER (brand MP)."""
    from apps.catalog.models import ProductVariant
    asked = [word for word in re.findall(r"[a-z0-9]+", name.lower()) if word not in {"the", "a", "an", "of", "for", "my"}]
    if not asked:
        return []
    scored = []
    for v in ProductVariant.objects.filter(product__active=True).select_related("product__brand", "product__category")[:5000]:
        words = " ".join([v.product.name, v.name, v.sku or "", v.product.brand.name if v.product.brand_id else "", v.product.category.name])
        tokens = set(re.findall(r"[a-z0-9]+", words.lower()))
        score = sum(_word_score(word, tokens) for word in asked) / len(asked)
        if score >= 0.8 and v.sku:
            scored.append((score, v.sku))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [sku for score, sku in sorted(scored, key=lambda x: -x[0]) if score >= best - 0.05][:limit]


def _lookup(w, name):
    """find_products for a name, trying harder when it finds nothing: the products whose words best match the words
    asked, allowing for misspellings and brands ("mp chager"), then the longer words one by one."""
    data = w.call("find_products", {"query": name, "limit": 10})
    if data is None or data["products"]:
        return data
    found = []
    for sku in closest_products(name):
        rows = (w.call("find_products", {"query": sku, "limit": 3}) or {"products": []})["products"]
        found += [row for row in rows if row not in found]
    if found:
        return {**data, "products": found[:10]}
    for word in sorted(name.split(), key=len, reverse=True):
        if len(word) > 2:
            matched = w.call("find_products", {"query": word, "limit": 10})
            if matched and matched["products"]:
                return matched
    return data


def product(w, text):
    name = product_name(text)
    if not name:
        return None
    data = _lookup(w, name)
    if data is None:
        return w.problem
    if not data["products"]:
        return f"I couldn't find a product matching \"{name}\". Check the spelling, or search on the Products page."
    found = data["products"]
    offer = re.search(OFFER, text)
    if offer and len(found) == 1:
        return offered_price(w, found[0], float(offer.group(1).replace(",", "")))
    if re.search(LOWEST, text) and re.search(r"\b(price|pay|sell|go|charge|accept|take)\b", text):
        return lowest_price(w, found)
    counted = [p for p in found if p.get("available") is not None]
    if counted and re.search(r"\b(how many|how much stock|available|left|in stock|do (i|we) have)\b", text):
        units = sum(max(p["available"], 0) for p in counted)
        in_stock = sum(1 for p in counted if p["available"] > 0)
        lines = [f"**{units:g} {name} available** across {in_stock} of {len(found)} product{'s' if len(found) != 1 else ''}:", ""]
    else:
        lines = [f"**{len(found)} match{'es' if len(found) != 1 else ''} for \"{name}\":**", ""]
    show_stock = any(p.get("available") is not None for p in found)
    show_cost = any(p.get("average_unit_cost") is not None for p in found)
    rows = []
    for p in found:
        low_price = p.get("lowest_price_allowed")
        # The range a sale can be made in: down to the lowest price allowed, up to the selling price.
        price = (f"{w.money(low_price)}–{(p['selling_price'] or 0):,.0f}" if low_price and low_price < (p["selling_price"] or 0)
                 else w.money(p["selling_price"]))
        stock = ("**out**" if p["available"] <= 0 else f"{p['available']:g}" + (" low" if p.get("minimum_stock") and p["available"] <= p["minimum_stock"] else "")
                 ) if p.get("available") is not None else "—"
        rows.append([p["product"] + ("" if p["active"] else " (inactive)")] + ([stock] if show_stock else []) + [price]
                    + ([w.money(p["average_unit_cost"]) if p.get("average_unit_cost") is not None else "—"] if show_cost else []))
    lines += table(["Product"] + (["Left"] if show_stock else []) + ["Sell for"] + (["Cost"] if show_cost else []), rows)
    if any(p.get("lowest_price_allowed") for p in found):
        lines += ["", "> **Sell for** is the range you can sell in: from the lowest price allowed up to the normal selling price."]
    return "\n".join(lines)


def lowest_price(w, found):
    """The lowest price each matching product can be sold at, and its normal price."""
    lines = []
    for p in found[:5]:
        low, normal = p.get("lowest_price_allowed"), p["selling_price"] or 0
        if low and low < normal:
            lines.append(f"- **{p['product']}**: lowest **{w.money(low)}**, normal price {w.money(normal)}")
        else:
            lines.append(f"- **{p['product']}**: **{w.money(normal)}**; no lower price is allowed (no bargaining price is set)")
    head = ("**The lowest price a customer can pay:**" if len(lines) > 1 else lines[0].replace("- ", "", 1))
    out = [head] + (["", *lines] if len(lines) > 1 else [])
    if any(not p.get("lowest_price_allowed") for p in found[:5]):
        out += ["", "> To allow bargaining, set a **lowest price** on the product (Products → edit the item)."]
    return "\n".join(out)


def offered_price(w, p, offered):
    """Whether a price offered for a product can be accepted: at or above the lowest price allowed."""
    low, normal = p.get("lowest_price_allowed") or 0, p["selling_price"] or 0
    floor = low if low and low < normal else normal
    if offered >= normal:
        return f"**Yes.** {w.money(offered)} is at or above the normal price of **{p['product']}** ({w.money(normal)})."
    if offered >= floor:
        return (f"**Yes.** {w.money(offered)} is within the bargaining range for **{p['product']}**: lowest {w.money(floor)}, "
                f"normal {w.money(normal)}.")
    return (f"**No.** {w.money(offered)} is below the lowest price for **{p['product']}**, which is **{w.money(floor)}** "
            f"(normal {w.money(normal)}). A sale below it is noted for the owner to review.")


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


def chamas(w, text):
    data = w.call("chamas")
    if data is None:
        return w.problem
    if not data["chamas"]:
        return "No chama is registered in this business yet. Open **Chama → My chama** to set one up."
    named = next((c for c in data["chamas"] if c["name"].lower() in text), None)
    if named or len(data["chamas"]) == 1 and re.search(r"\b(members?|who|whose|paid|owe|late|turns?|receive|receives|fines?|next)\b", text):
        return chama_members(w, text, (named or data["chamas"][0])["name"])
    lines = [f"**{len(data['chamas'])} chama{'s' if len(data['chamas']) != 1 else ''} registered:**", ""]
    for c in data["chamas"]:
        turn = f"; next to receive: {c['next_turn']['member']} on {c['next_turn']['date']}" if c.get("next_turn") else ""
        lines.append(f"- **{c['name']}**: {c['members']} members, {w.money(c['contribution_amount'])} {c['frequency'].lower()}, "
                     f"holding {w.money(c['held'])}; this period {c['paid_count']} of {c['due_count']} paid, {c['late_count']} late{turn}")
    return "\n".join(lines)


def chama_members(w, text, name=None):
    data = w.call("chama_members", {"chama": name} if name else {})
    if data is None:
        return w.problem
    if not data["chama"]:
        return "No chama is registered in this business yet. Open **Chama → My chama** to set one up."
    active = [m for m in data["members"] if m["active"]]
    money = data["money"]
    lines = [f"**{data['chama']}** has {len(active)} member{'s' if len(active) != 1 else ''} "
             f"({w.money(data['contribution'])} {data['frequency'].lower()}). It holds **{w.money(money['held'])}**; "
             f"members still owe {w.money(money['unpaid'])} ({w.money(money['late'])} late) and {w.money(money['fines_owed'])} in fines.", "", "### Members"]
    if re.search(r"\b(late|owe|owing|not paid|haven'?t paid|unpaid|defaulters?)\b", text):
        behind = [m for m in active if (m["unpaid"] or 0) > 0 or (m["fines_owed"] or 0) > 0]
        lines += [f"- {m['name']}: owes {w.money(m['unpaid'])}" + (f" ({w.money(m['late'])} late)" if m["late"] else "")
                  + (f", fines {w.money(m['fines_owed'])}" if m["fines_owed"] else "") for m in behind] or ["Everyone is up to date."]
    else:
        # In turn order: whoever receives first is listed first.
        for m in sorted(active, key=lambda m: (m["next_turn"] or "9999-12-31", m["name"].lower())):
            extra = [m["role"]] if m["role"] and m["role"].lower() != "member" else []
            extra.append(f"paid in {w.money(m['paid_in'])}")
            if m["unpaid"]:
                extra.append(f"owes {w.money(m['unpaid'])}")
            if m["next_turn"]:
                extra.append(f"next turn {timezone.datetime.fromisoformat(m['next_turn']).strftime('%a %d %b %Y')}")
            lines.append(f"- {m['name']}: {', '.join(extra)}")
    if data.get("next_turns"):
        per = data["contributions_per_turn"]
        lines += ["", f"### Turns ({per} {data['frequency'].lower()} contribution{'s' if per != 1 else ''} each)"]
        lines += table(["Turn", "Member", "Date", "Receives"], [[t["turn"], t["member"], timezone.datetime.fromisoformat(t["date"]).strftime("%a %d %b"),
                                                               w.money(t["receives"])] for t in data["next_turns"]])
        first = data["next_turns"][0]
        if first.get("collected_so_far") is not None:
            lines += ["", f"Collected so far for turn {first['turn']}: **{w.money(first['collected_so_far'])}** of {w.money(first['receives'])}."]
    if data.get("turns_given"):
        last = data["turns_given"][-1]
        lines.append(f"- Last given: turn {last['turn']} to {last['member']}, {w.money(last['received'])} on {last['on']}")
    return "\n".join(lines)


def investments(w, text):
    data = w.call("investments")
    if data is None:
        return w.problem
    if not data["investments"]:
        return "No investments are recorded. Add one on the **Investments** page."
    lines = [f"**Investments are worth {w.money(data['total_value'])}** in total.", ""]
    lines += [f"- {i['investment']}: {w.money(i['value_now'])} (put in {w.money(i.get('DEPOSIT'))}, taken out {w.money(i.get('WITHDRAWAL'))}, "
              f"interest {w.money(i.get('INTEREST'))}, fees {w.money(i.get('FEE'))})" for i in data["investments"]]
    return "\n".join(lines + ["", data["explained"]])


def service_jobs(w, text):
    start, end, words = period(text, 30)
    data = w.call("service_jobs", {**_args(start, end), "limit": 10})
    if data is None:
        return w.problem
    jobs = data["jobs_by_status"]
    if not jobs:
        return f"No service jobs in {words}."
    lines = [f"**{sum(jobs.values())} service jobs** in {words}, completed value {w.money(data['completed_value'])}.", "",
             "- By status: " + ", ".join(f"{k.replace('_', ' ').lower()} {v}" for k, v in jobs.items())]
    if data.get("open_jobs_overdue_now"):
        lines.append(f"- **{data['open_jobs_overdue_now']} open job(s) are overdue now**")
    if data.get("top_services"):
        lines += ["", "Top services:"] + [f"- {t['service']}: {t['jobs']} job{'s' if t['jobs'] != 1 else ''}, {w.money(t['value'])}" for t in data["top_services"]]
    return "\n".join(lines)


def purchases(w, text):
    start, end, words = period(text, 30)
    data = w.call("purchases_and_suppliers", {**_args(start, end), "limit": 10})
    if data is None:
        return w.problem
    if not data["by_supplier"]:
        return f"No stock was bought from suppliers in {words}."
    lines = [f"**Bought {w.money(data['total_bought'])} of stock** in {words}.", ""]
    lines += [f"- {r['supplier']}: {w.money(r['bought'])} over {r['purchases']} purchase(s)" + (f", still owed {w.money(r['still_owed'])}" if r["still_owed"] else "")
              for r in data["by_supplier"]]
    return "\n".join(lines)


def staff_activity(w, text):
    start, end, words = period(text, 7)
    lines = []
    sold = w.call("sales_summary", {**_args(start, end), "group_by": "staff"})
    if sold and sold["rows"]:
        lines += [f"**Sales by staff, {words}:**"] + [f"- {r['staff']}: {r['sales']} sales, {w.money(r['value'])}" for r in sold["rows"]] + [""]
    log = w.call("activity_log", {**_args(start, end), "limit": 10})
    if log:
        lines += [f"**Activity, {words}:** {log['total_actions']} recorded actions."]
        lines += [f"- {p['person']}: {p['actions']} action{'s' if p['actions'] != 1 else ''}" for p in log["by_person"]]
        if log["latest"]:
            lines += ["", "Latest:"] + [f"- {a['when']}: {a['who']}: {a['action'].replace('_', ' ').lower()}" for a in log["latest"][:8]]
    return "\n".join(lines) or w.problem


def stock_changes(w, text):
    start, end, words = period(text, 30)
    data = w.call("stock_movements", {**_args(start, end), "limit": 10})
    if data is None:
        return w.problem
    lines = [f"**Stock adjustments** in {words}: {data['units_removed_by_adjustments']:g} units removed, {data['units_sold']:g} sold"
             + (f" (shrinkage {data['shrinkage_rate_pct']}%)." if data.get("shrinkage_rate_pct") is not None else ".")]
    if data["adjustments_by_reason"]:
        lines += ["", "By reason:"] + [f"- {r['reason'].replace('_', ' ').lower()}: {r['count']} times, {r['units']:g} units" for r in data["adjustments_by_reason"]]
    if data["recent_adjustments"]:
        lines += ["", "Latest:"] + [f"- {a['when']}: {a['product']} {a['change']:+g} ({a['reason'].replace('_', ' ').lower()}, by {a['by']})"
                                    for a in data["recent_adjustments"][:8]]
    return "\n".join(lines)


def sale_lookup(w, text):
    number = re.search(r"\b((?:pos|cyb|onl|sal)-[a-z0-9-]+)\b", text)
    customer = None if number else re.search(r"\b(?:customer|did|has|have)\s+([a-z][a-z .'-]{1,40}?)\s+(?:buy|bought|owe|purchase|spent)", text)
    if customer and customer.group(1).strip() in {"customers", "customer", "people", "clients", "they", "we", "i", "you", "anyone", "someone"}:
        customer = None
    args = {"sale_number": number.group(1).upper()} if number else {"customer": customer.group(1).strip()} if customer else None
    if not args:
        return None
    data = w.call("find_sales", {**args, "limit": 5})
    if data is None:
        return w.problem
    if not data["sales"]:
        return f"No sale found for {args.get('sale_number') or args.get('customer')}."
    lines = []
    history = data.get("customer_history")
    if history:
        lines += [f"**{data['sales'][0]['customer']}** has bought {history['completed_sales']} time{'s' if history['completed_sales'] != 1 else ''}, {w.money(history['total_spent'])} in total "
                  f"since {history['first_purchase']}.", ""]
    for sale in data["sales"]:
        items = ", ".join(f"{i['product']} × {i['quantity']:g}" for i in sale["items"])
        owed = f", **still owes {w.money(sale['still_owed'])}**" if sale["still_owed"] and sale["still_owed"] > 0 else ""
        lines.append(f"- {sale['number']} on {sale['when']} by {sale['sold_by']}: {w.money(sale['total'])} ({items}){owed}")
    return "\n".join(lines)


def business_profile(w, text):
    data = w.call("business_overview")
    sub = data.get("subscription") or {}
    lines = [f"**{data['business']}** ({data['business_type']}), {data['country']}, money in {data['currency']}. Records start {data['records_start']}.", "",
             f"- Branches: {', '.join(data['branches']) or 'none'}", f"- Staff members: {data['staff_members']}",
             f"- Plan: {sub.get('plan') or 'none'} ({(sub.get('status') or '').lower()}" + (f", until {sub['ends']}" if sub.get("ends") else "") + ")",
             f"- Tools enabled: {', '.join(data['modules_enabled'])}"]
    if data.get("catalog"):
        c = data["catalog"]
        lines.append(f"- Catalogue: {c['active_products']} products ({c['active_variants']} variants, {c['services']} services) in {c['categories']} categories")
    return "\n".join(lines)


def platform(w, text):
    data = w.call("platform_overview")
    if data is None:
        return None  # not the platform administrator: treat it as an ordinary question
    s = data["summary"]
    lines = [f"**{s['businesses']} businesses are registered**: {s['trial']} on trial, {s['paying']} paying, {s['complimentary']} free, "
             f"{s['ended']} ended, {s['expiring_soon']} expiring soon. Revenue this month {w.money(s['revenue_this_month'])}, "
             f"{w.money(s['revenue_total'])} in total.", ""]
    listed = w.call("platform_businesses", {"limit": 20}) or {"businesses": []}
    lines += [f"- {b['business']} ({b['type'] or 'business'}), owner {b['owner']['name'] or b['owner']['username']}: {b['plan'] or 'no plan'}, "
              f"{b['status'].lower()}" + (f", {b['days_left']} days left" if b.get("days_left") is not None else "")
              + f"; last active {b['last_activity'] or 'never'}" for b in listed["businesses"]]
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


def market_prices(w, text):
    """Comparing prices with other shops needs the internet, which only the AI assistant can search: say so plainly
    rather than reading the question as something it is not."""
    return ("**Other shops' prices can't be checked right now.** Your records only hold your own prices.\n\n"
            "Ask for any product's price here (e.g. *price of HDMI cable*) to see what you sell it for and the lowest price allowed.")


FALLBACK = ("I didn't quite get that. I can tell you: which items are in stock; a product's stock and price; chamas and their "
            "members; investments and loans; service jobs; purchases from suppliers; staff activity; stock adjustments; a sale by its "
            "number or what a customer bought; your business profile; sales today, this week or this month; how sales are trending; profit and "
            "loss; busiest days and hours; top products; what is running low; stock that has not sold; stock value; who owes you; "
            "what you owe; where your money is (net worth); expenses; top customers; M-Pesa agency and commission; and how to do "
            "something in the app. Try asking one of those.")

# (pattern, answer). The first match wins, so the more specific questions come first.
INTENTS = [
    (r"\b(retailers?|competitors?|other (shops|stores|sellers)|market (price|rate)s?|jumia|kilimall|carrefour|naivas|quickmart"
     r"|compare (my |our |the )?(prices?|sp|selling prices?)|(prices?|sp) (compared?|against|vs\.?|versus))\b", market_prices),
    (OFFER + r"\s*(for|of)\b|\b(?:sell|charge)\b.+\b(?:for|at)\s*(?:kes|ksh|sh)?\s*\d", product),
    (r"\bwhat (did|have|do) ((customers?|people|clients?) (buy|bought)|(we|i) (sell|sold))\b", top_products),
    (r"^(how (do|can|should) i|how to|where (do|can) i|can i|is it possible|what is the way)\b", help_answer),
    # A product's price ("lowest price a customer can pay for the MP charger"), before "customer" reads it as a customers question.
    (LOWEST + r".*\b(price|pay|sell|charge|go for|accept|take)\b|\bprices? (for|of)\b", product),
    (r"\b(which|what) (items|products|goods|stock)\b.*\b(in stock|available|do i have|have i got|are there|left)\b"
     r"|\b(items|products|goods|everything|what is|what's) (in stock|available)\b|\b(list|show)( me)? (my |all |the )?(stock|items|products|inventory)\b"
     r"|\bstock list\b|\bwhat do (i|we) have\b", stock_list),
    (r"\b(trend|trending|forecast|grow|growing|growth|predict|going up|going down|declin)", sales_trend),
    (r"\b(busiest|busy|peak|quiet|which day|what day|best day|hours?)\b", busiest),
    (r"\b(profit|loss|p&l|p ?and ?l|income statement|margin|net income|making money)\b", profit_and_loss),
    (r"\b(not sold|haven'?t sold|has not sold|hasn'?t sold|dead stock|slow[- ]moving|not selling|unsold)\b", dead_stock),
    (r"\b(running low|low stock|reorder|re-order|restock|out of stock|running out|need to buy|order more)\b", reorder),
    (r"\b(owes? me|owe us|who owes|debtors?|credit sales|unpaid sales|receivables?|lent|loans?)\b", owed_to_me),
    # What the business bought from suppliers; "which customers bought ..." is about customers, further down.
    (r"^(?!.*\b(customers?|clients?)\b).*(\b(buy|bought|purchases?|purchased|stock received|received stock)\b.*\b(suppliers?|stock|this|last|today|week|month)\b"
     r"|\b(purchases?|purchased|stock received|received stock)\b)", purchases),
    (r"\b(i owe|we owe|do i owe|suppliers?|payables?|bills?|creditors?)\b", i_owe),
    (r"\b(net worth|worth|where is (my|the) money|how much money|cash|bank|balances?|assets?)\b", money_position),
    (r"\b(expenses?|spent|spending|running costs?|costs?)\b", expenses),
    (r"\b(shift|deposits?|withdrawals?|withdraw|reversals?|reversed)\b|\bm-?pesa transactions?\b", mpesa_shift),
    (r"\b(commission|m-?pesa|float|agency|agent)\b", agency),
    (r"\b(top|best[- ]selling|best sellers?|most (revenue|sales|money)|bring in|popular)\b.*\b(products?|items?|sellers?|revenue)?", top_products),
    (r"\b(customers?|clients?|buyers?)\b", customers),
    (r"\b(chamas?|savings group|merry[- ]go[- ]round|umoja|contributions?|table banking|whose turn|receives? next)\b", chamas),
    (r"\b(businesses (are )?registered|registered businesses|all businesses|how many businesses|subscribers|platform revenue)\b", platform),
    (r"\b(investments?|mmf|money market|unit trust)\b", investments),
    (r"\b(service jobs?|jobs|repairs?|printing jobs|job cards?)\b", service_jobs),
    (r"\b(staff|employees?|workers?|cashiers?|who sold|who did|activity|audit)\b", staff_activity),
    (r"\b(adjust(ed|ments?)?|damaged|lost|stolen|shrinkage|stock movements?)\b", stock_changes),
    (r"\b(my business|business profile|about (my|the) business|branches|subscription|my plan)\b", business_profile),
    (r"\b(stock value|value of (my )?stock|how much stock|stock on hand|inventory)\b", stock_value),
    (r"\b(do (i|we) (have|stock|sell)|how many .+ (have|left|in stock|available)|(is|are) (there )?(any )?.+ (in stock|available|left)"
     r"|price of|how much (is|does|do)|find|look up|search for|check)\b", product),
    (r"\b(sales|sold|revenue|turnover|sell|takings)\b", sales),
]


def answer(ctx, question):
    """(markdown answer, tools used). Runs inside the business's scope."""
    text = " ".join(question.lower().split())
    w = Writer(ctx)
    looked_up = sale_lookup(w, text)
    if looked_up:
        return looked_up, w.used
    for pattern, handler in INTENTS:
        if re.search(pattern, text):
            result = handler(w, text)
            if result:
                return result, w.used
    if re.search(r"\b(stock|items?|products?|goods)\b", text):
        return stock_list(w, text), w.used
    found = help_answer(w, text)
    return (found or FALLBACK), w.used
