"""Everything an owner wants to know about one product on one page: where it sits in the categories, its stock
and what that stock is worth, how it has been selling, where it came from and what has happened to it."""
from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone

ZERO = Decimal("0")
# Plain names for stock movements; "in" adds to the shelves, "out" takes away, "moved" changes shelf only.
MOVEMENTS = {"OPENING_STOCK": "Opening stock entered", "PURCHASE_RECEIPT": "Received from supplier", "SALE": "Sold",
             "ONLINE_ORDER": "Sold online", "CYBER_CONSUMPTION": "Used in a service", "TRANSFER": "Moved to another shelf",
             "CUSTOMER_RETURN": "Returned by customer", "SALE_RETURN": "Returned by customer", "SUPPLIER_RETURN": "Returned to supplier",
             "PURCHASE_RETURN": "Returned to supplier", "DAMAGE": "Damaged", "LOSS": "Lost", "STOCKTAKE_ADJUSTMENT": "Stock count correction",
             "STOCK_ADJUSTMENT": "Stock adjustment", "MANUAL_ADJUSTMENT": "Stock adjustment", "ORDER_RESERVATION": "Set aside for an order",
             "RESERVATION_RELEASE": "Released from an order", "OTHER": "Other"}


def category_path(category):
    path = []
    while category is not None:
        path.insert(0, category.name)
        category = category.parent
    return path


def product_overview(product, show_cost):
    from apps.commerce.models import SaleItem
    from apps.commerce.returns import item_sales
    from apps.inventory.models import Movement, StockBalance, StockLot
    variants = list(product.variants.all())
    balances = StockBalance.objects.filter(lot__variant__in=variants).select_related("lot", "lot__variant")
    on_shelf = sum((b.quantity for b in balances), ZERO)
    reserved = sum((b.reserved for b in balances), ZERO)
    retail = sum((b.quantity * b.lot.variant.selling_price for b in balances), ZERO)
    cost = sum((b.quantity * b.lot.unit_cost for b in balances), ZERO)

    since = timezone.now() - timedelta(days=30)
    def sales(items):
        quantity = revenue = spent = ZERO
        for item in items:
            kept_quantity, kept_amount = item_sales(item.sale).get(item.pk, (item.quantity, item.net_amount))
            quantity += kept_quantity
            revenue += kept_amount
            spent += item.cost * (kept_quantity / item.quantity) if item.quantity else ZERO
        row = {"quantity": quantity, "revenue": revenue}
        if show_cost:
            row.update(cost=spent.quantize(Decimal("0.01")), profit=(revenue - spent).quantize(Decimal("0.01")))
        return row
    sold = SaleItem.objects.filter(variant__in=variants, sale__status="COMPLETED").select_related("sale")
    last_sale = sold.order_by("-sale__created_at").first()
    lots = StockLot.objects.filter(variant__in=variants).select_related("variant").order_by("-received_at", "-pk")
    deliveries = [{"date": lot.received_at, "reference": lot.reference, "supplier": lot.supplier_name, "variant": lot.variant.name,
                   "received": lot.received_quantity, "left": lot.remaining_quantity, **({"cost_each": lot.unit_cost} if show_cost else {})}
                  for lot in lots[:8]]
    activity = []
    for move in Movement.objects.filter(variant__in=variants).select_related("source", "destination", "performed_by", "variant").order_by("-created_at", "-pk")[:15]:
        direction = "moved" if move.source_id and move.destination_id else "in" if move.destination_id else "out"
        activity.append({"date": move.created_at, "what": MOVEMENTS.get(move.movement_type, move.movement_type.replace("_", " ").title()),
                         "direction": direction, "quantity": abs(move.quantity), "reference": move.reference, "variant": move.variant.name,
                         "shelf": (move.destination or move.source).code if (move.destination or move.source) else "",
                         "by": (move.performed_by.get_full_name() or move.performed_by.username) if move.performed_by else ""})
    cents = Decimal("0.01")
    stock = {"on_shelf": on_shelf, "reserved": reserved, "available": on_shelf - reserved, "value_at_selling_price": retail.quantize(cents)}
    if show_cost:
        stock.update(value_at_cost=cost.quantize(cents), potential_profit=(retail - cost).quantize(cents))
    return {"category_path": category_path(product.category), "stock": stock,
            "sales_30_days": sales(sold.filter(sale__created_at__gte=since)), "sales_all_time": sales(sold),
            "last_sold": last_sale.sale.created_at if last_sale else None, "last_received": lots[0].received_at if lots else None,
            "deliveries": deliveries, "activity": activity}


def stock_totals(show_cost):
    """All the stock the business holds now, for the top of the Products page: how many items, how many products have
    stock, and what it is worth at selling price and (for those who may see costs) at what it cost. Worked out from the
    shelves, so it goes up when stock is received or returned and down when it is sold, used, lost or sent back. Stock
    received without a buying price is counted at selling price only, and how many such lots there are is given."""
    from django.db.models import DecimalField, ExpressionWrapper, F
    from apps.inventory.models import StockBalance, StockLot
    held = StockBalance.objects.filter(quantity__gt=0, lot__variant__active=True, lot__variant__product__active=True,
                                       lot__variant__product__product_type="STOCK_ITEM")
    money = lambda price: Sum(ExpressionWrapper(F("quantity") * price, output_field=DecimalField()))
    totals = held.aggregate(units=Sum("quantity"), retail=money(F("lot__variant__selling_price")),
                            cost=money(F("lot__unit_cost")))
    cents = Decimal("0.01")
    result = {"units": totals["units"] or ZERO, "products": held.values("lot__variant__product_id").distinct().count(),
              "value_at_selling_price": (totals["retail"] or ZERO).quantize(cents)}
    if show_cost:
        uncosted = held.filter(lot__cost_status=StockLot.UNCOSTED)
        cost = (totals["cost"] or ZERO) - (uncosted.aggregate(v=money(F("lot__unit_cost")))["v"] or ZERO)
        result.update(value_at_cost=cost.quantize(cents), cost_missing=uncosted.values("lot_id").distinct().count())
    return result
