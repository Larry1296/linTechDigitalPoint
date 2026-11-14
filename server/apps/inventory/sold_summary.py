"""What the business has brought in since it started, by what it was: goods, services, commission and interest.

The amounts are the books' own (the same rows as the profit figures, so the two always agree); the counts beside them
(sales, items, nights, phones) come from the records. A line shows when the business uses the tool behind it, or when
something was ever recorded on it. Parts the viewer may not see are left out, never guessed; interest is shown only to
someone who may see profit, like everywhere else."""
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

ZERO = Decimal("0")

# (key, name, part, [(account, line name, tool that makes it)]). A part of None means each line's own part.
GROUPS = [
    ("GOODS", "Goods", "SHOP", [("4000", "Products", "inventory"), ("4030", "Food & drinks", "menu")]),
    ("SERVICES", "Services", "CYBER", [("4020", "Services", "services"), ("4040", "Rooms & guests", "rooms")]),
    ("COMMISSION", "Commission", None, [("4010", "M-Pesa agency", "mpesa"), ("4050", "M-KOPA phones", "mkopa")]),
    ("INTEREST", "Interest", "INVEST", [("4910", "Interest earned", "investments"), ("6200", "Fund fees and losses", None)]),
    ("OTHER", "Other income", "SHOP", [("4900", "Other income", None)]),
]
LINE_PART = {"4010": "MPESA", "4050": "MKOPA"}


def _amounts(rows):
    """{account: amount brought in} from the dashboard's rows: revenue, and interest less the fund's fees."""
    totals = {}
    for row in rows:
        if row["field"] in ("revenue", "interest"):
            totals[row["code"]] = totals.get(row["code"], ZERO) + row["amount"]
    return totals


def _item_counts(units):
    """{account: (sales, quantity)} for completed sales since the start, split the way the books split revenue: a dish
    from the menu and a room night apart from other services. Returned items are taken off."""
    from apps.commerce.models import Sale, SaleItem
    from apps.hotel.models import MenuItem, RoomType
    channels = ([Sale.POS, Sale.ONLINE] if "SHOP" in units else []) + ([Sale.CYBER] if "CYBER" in units else [])
    if not channels:
        return {}
    items = SaleItem.objects.filter(sale__status="COMPLETED", sale__channel__in=channels)
    menu = MenuItem.objects.values("variant_id")
    rooms = RoomType.objects.values("variant_id")
    kinds = {"4000": items.filter(variant__product__product_type="STOCK_ITEM"),
             "4030": items.filter(variant_id__in=menu),
             "4040": items.filter(variant_id__in=rooms),
             "4020": items.filter(variant__product__product_type="SERVICE").exclude(variant_id__in=menu).exclude(variant_id__in=rooms)}
    counts = {}
    for code, rows in kinds.items():
        sold = rows.aggregate(q=Sum(F("quantity") - F("returned_quantity")))["q"] or ZERO
        counts[code] = (rows.values("sale_id").distinct().count(), sold)
    return counts


def _mpesa_detail(profit_visible):
    """Months Safaricom has paid commission for, and the commission the app works out for months it has not paid yet."""
    from apps.mpesa.commission_learning import unpaid
    from apps.mpesa.models import MpesaCommissionEntry, MpesaSession
    paid = MpesaCommissionEntry.objects.filter(reversed_at__isnull=True).values("period").distinct().count()
    first = MpesaSession.objects.order_by("opened_at").values_list("opened_at", flat=True).first()
    coming = unpaid(timezone.localtime(first).date(), timezone.localdate()) if first and profit_visible else {"amount": ZERO, "months": []}
    return {"months_paid": paid, "coming": coming["amount"], "coming_months": coming["months"]}


def _mkopa_detail():
    """Phones sold, and the commission still expected on phones M-KOPA has not paid for."""
    from apps.mkopa.models import MkopaSale
    sales = MkopaSale.objects.filter(reversed_at__isnull=True)
    waiting = sales.filter(paid_by__isnull=True)
    return {"phones": sales.count(), "waiting_phones": waiting.count(),
            "coming": waiting.aggregate(v=Sum("commission"))["v"] or ZERO}


def sold_since_start(rows, *, units, enabled, profit_visible):
    """{"groups": [{"key", "name", "amount", "lines": [{"code", "name", "amount", ...counts}]}], "total"}, or None when
    the viewer may see no part. ``rows`` are the dashboard's since-the-start rows, already limited to what they may see."""
    if not units:
        return None
    amounts = _amounts(rows)
    counts = _item_counts(units)
    groups, total = [], ZERO
    for key, name, part, lines in GROUPS:
        if key == "INTEREST" and not profit_visible:
            continue
        shown = []
        for code, line_name, tool in lines:
            line_part = LINE_PART.get(code, part)
            if line_part != "INVEST" and line_part not in units:
                continue
            amount = amounts.get(code, ZERO)
            if not amount and tool not in enabled:
                continue
            line = {"code": code, "name": line_name, "amount": amount}
            if code in counts:
                line["sales"], line["quantity"] = counts[code]
            if code == "4010":
                line.update(_mpesa_detail(profit_visible))
            if code == "4050":
                line.update(_mkopa_detail())
            shown.append(line)
        if shown:
            amount = sum((line["amount"] for line in shown), ZERO)
            groups.append({"key": key, "name": name, "amount": amount, "lines": shown})
            total += amount
    return {"groups": groups, "total": total}


# The business's own places, as on the Money check page; the agency's own cash and float are never among them.
OWNER_PLACES = ("CASH", "MPESA", "BANK", "OTHER")


def money_bridge(sold_total, interest):
    """How what was brought in became the business's money now, for someone who may see the business's money: every
    line is the cash book of the business's own places grouped by what it was, so the bridge always ends exactly at
    what those places should hold plus the business's money kept in investments (the Money check and Investments pages).

    Interest is earned inside the investment, never through a place; what was sold but not received yet is what was
    brought in less what was received and less that interest. {"lines": [{"key", "amount"}], "money_now", "in_places",
    "in_investments", "interest"}; a line's amount is added (negative takes away)."""
    from apps.accounting.models import CashEntry
    from apps.accounting.money_check import kept_in_investments
    entries = CashEntry.objects.filter(account__payment_method__in=OWNER_PLACES)
    by_kind = {kind: amount or ZERO for kind, amount in entries.values_list("kind").annotate(v=Sum("amount"))}
    opening = entries.filter(kind="OPENING")
    own = opening.filter(source_key__startswith="owner-pays:").aggregate(v=Sum("amount"))["v"] or ZERO
    found = opening.filter(source_key__startswith="investment-cover:").aggregate(v=Sum("amount"))["v"] or ZERO
    starting = by_kind.get("OPENING", ZERO) - own - found
    received = by_kind.get("INCOME", ZERO)
    interest = interest or ZERO
    lines = [("not_received", -(sold_total - interest - received)), ("starting", starting), ("own_for_suppliers", own),
             ("found", found), ("agency", by_kind.get("TRANSFER", ZERO)), ("suppliers", by_kind.get("PURCHASE", ZERO)),
             ("expenses", by_kind.get("EXPENSE", ZERO)), ("loans", by_kind.get("LOAN", ZERO)),
             ("other", sum((v for k, v in by_kind.items() if k not in {"INCOME", "OPENING", "TRANSFER", "PURCHASE", "EXPENSE", "LOAN", "INVESTMENT"}), ZERO))]
    in_places = sum(by_kind.values(), ZERO)
    invested = kept_in_investments()["total"]
    return {"lines": [{"key": key, "amount": amount} for key, amount in lines if amount],
            "money_now": in_places + invested, "in_places": in_places, "in_investments": invested, "interest": interest}
