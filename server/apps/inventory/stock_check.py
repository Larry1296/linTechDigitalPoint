"""Count every product at once and settle the differences.

Missing items are either sold (recorded as a sale through the till, so money and profit come in) or lost
(a loss, through a stock adjustment). Extra items are found stock (added to stock, never to profit).
Adjustments go shelf by shelf through adjust_stock, so every rule and record of a normal adjustment applies.
"""
from decimal import Decimal
from uuid import uuid4
from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from apps.catalog.models import Product, ProductVariant
from .adjustments import adjust_stock
from .models import StockBalance, StockLot

ZERO = Decimal("0")


def products(show_cost):
    rows = []
    variants = ProductVariant.objects.filter(active=True, product__active=True, product__product_type=Product.STOCK_ITEM).select_related("product").order_by("product__name", "name")
    for v in variants:
        balances = list(StockBalance.objects.filter(lot__variant=v, quantity__gt=0).select_related("lot", "shelf").order_by("lot__received_at", "lot_id"))
        next_lot = balances[0].lot if balances else StockLot.objects.filter(variant=v).order_by("-received_at", "-pk").first()
        row = {"id": v.pk, "name": v.product.name, "variant": v.name, "sku": v.sku, "on_shelf": sum((b.quantity for b in balances), ZERO),
               "reserved": sum((b.reserved for b in balances), ZERO), "selling_price": v.selling_price, "lowest_price": v.minimum_price}
        if show_cost:
            # The buying price of the next unit to leave the shelf (oldest delivery first), which a sale would use.
            row["buying_price"] = next_lot.unit_cost if next_lot else None
        rows.append(row)
    return rows


@transaction.atomic
def record_difference(*, user, variant_id, quantity, reason, unit_cost=None, note=""):
    """Takes `quantity` units off (negative) or puts them on (positive), across the shelves holding the item."""
    quantity = Decimal(str(quantity))
    if not quantity:
        raise ValidationError("Enter how many are missing or extra.")
    variant = ProductVariant.objects.filter(pk=variant_id).first()
    if not variant:
        raise ValidationError("Choose a product.")
    batch = uuid4().hex[:12]
    adjustments = []
    if quantity < 0:
        need = -quantity
        shelves = (StockBalance.objects.filter(lot__variant=variant, quantity__gt=0).values("shelf_id")
                   .annotate(q=Sum("quantity"), r=Sum("reserved")).order_by("-q"))
        for index, shelf in enumerate(shelves):
            take = min(need, shelf["q"] - shelf["r"])
            if take <= 0:
                continue
            adjustments.append(adjust_stock(user=user, variant_id=variant.pk, shelf_id=shelf["shelf_id"], expected_quantity=shelf["q"],
                                            counted_quantity=shelf["q"] - take, reason=reason, idempotency_key=f"check-{batch}-{index}",
                                            confirmed=True, notes=note, reference="Stock check"))
            need -= take
            if not need:
                break
        if need:
            raise ValidationError(f"Only {-quantity - need} of these are on the shelves and not set aside for customers.")
    else:
        balance = StockBalance.objects.filter(lot__variant=variant).select_related("lot").order_by("-quantity", "-lot__received_at").first()
        shelf_id = balance.shelf_id if balance else None
        if not shelf_id:
            from .unplaced import unplaced_shelf
            shelf_id = unplaced_shelf().pk
        current = StockBalance.objects.filter(lot__variant=variant, shelf_id=shelf_id).aggregate(q=Sum("quantity"))["q"] or ZERO
        lot = balance.lot if balance and unit_cost in (None, "") else None
        if not lot and unit_cost in (None, ""):
            raise ValidationError("This item has no earlier delivery in the app. Enter its buying price.")
        adjustments.append(adjust_stock(user=user, variant_id=variant.pk, shelf_id=shelf_id, expected_quantity=current,
                                        counted_quantity=current + quantity, reason=reason, idempotency_key=f"check-{batch}-0",
                                        confirmed=True, notes=note, reference="Stock check", lot_id=lot.pk if lot else None,
                                        new_lot_unit_cost=None if lot else unit_cost))
    return adjustments
