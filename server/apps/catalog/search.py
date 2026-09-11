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


def variant_summary(v):
    return {"id": v.id, "product_id": v.product_id, "product_name": v.product.name,
            "variant_name": v.name, "category_id": v.product.category_id,
            "category_name": v.product.category.name, "sku": v.sku, "barcode": v.barcode,
            "product_type": v.product.product_type, "selling_price": v.selling_price}
