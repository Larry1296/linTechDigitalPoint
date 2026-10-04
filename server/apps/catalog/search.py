"""Shared internal variant search; public visibility rules remain separate."""
from django.db.models import Case, IntegerField, Q, Value, When


def search_variants(rows, query):
    query = query.strip()
    if query:
        match = Q()
        for field in ("product__name", "name", "product__category__name", "product__brand__name", "sku", "barcode"):
            match |= Q(**{field + "__icontains": query})
        rows = rows.filter(match).annotate(
            exact_rank=Case(When(Q(sku__iexact=query) | Q(barcode__iexact=query), then=Value(0)), default=Value(1), output_field=IntegerField())
        )
        return rows.order_by("exact_rank", "product__category__name", "product__name", "name", "id")
    return rows.order_by("product__category__name", "product__name", "name", "id")


def variant_summary(v, balances=None):
    from django.db.models import Sum
    from apps.inventory.models import StockBalance
    if balances is None:
        latest = v.lots.filter(pk__in=StockBalance.objects.values("lot_id")).order_by("-received_at", "-pk").first()
        locations = list(StockBalance.objects.filter(lot__variant=v, quantity__gt=0)
            .values("shelf__zone__name", "shelf__zone__store__name", "shelf__code", "shelf__display_name")
            .annotate(quantity=Sum("quantity")))
    else:
        latest = max((b.lot for b in balances), key=lambda lot:(lot.received_at,lot.pk), default=None)
        locations = [{"shelf__zone__name":b.shelf.zone.name, "shelf__zone__store__name":b.shelf.zone.store.name,
            "shelf__code":b.shelf.code,"shelf__display_name":b.shelf.display_name,"quantity":b.quantity} for b in balances if b.quantity > 0]
    available = sum((row["quantity"] for row in locations), 0)
    return {"id": v.id, "product_id": v.product_id, "product_name": v.product.name, "description": v.product.description,
            "variant_name": v.name, "category_id": v.product.category_id,
            "category_name": v.product.category.name, "sku": v.sku, "barcode": v.barcode,
            "product_type": v.product.product_type, "selling_price": v.selling_price, "minimum_price": v.minimum_price,
            "buying_price": latest.unit_cost if latest else v.service_cost, "available": available,
            "locations": [{"branch":row["shelf__zone__store__name"],"zone": row["shelf__zone__name"], "shelf_code": row["shelf__code"],
                           "shelf_name": row["shelf__display_name"], "quantity": row["quantity"]} for row in locations]}
