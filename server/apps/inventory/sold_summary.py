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
