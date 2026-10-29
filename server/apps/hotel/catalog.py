"""The products behind the hotel tools: a dish, a kind of room and a kitchen ingredient are catalogue items, so the till,
receipts, sales history and the books treat them like anything else sold or stocked."""
from uuid import uuid4

from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from apps.catalog.models import Category, Product, ProductVariant


def category(name):
    found = Category.objects.filter(name__iexact=name.strip()).first()
    if found:
        return found
    base = slugify(name)[:40] or "category"
    slug, number = base, 1
    while Category.objects.filter(slug=slug).exists():
        number += 1
        slug = f"{base}-{number}"
    return Category.objects.create(name=name.strip()[:120], slug=slug)


def new_variant(*, name, kind, group, price=0, unit="Standard", prefix="H"):
    """A product with its one variant. Not shown in an online shop: a plate or a night is sold in person."""
    name = " ".join(str(name or "").split())
    if not name:
        raise ValidationError("Enter a name.")
    base = slugify(name)[:40] or "item"
    slug, number = base, 1
    while Product.objects.filter(slug=slug).exists():
        number += 1
        slug = f"{base}-{number}"
    product = Product.objects.create(name=name[:180], slug=slug, category=category(group), product_type=kind,
                                     ecommerce_visible=False, online_orderable=False)
    return ProductVariant.objects.create(product=product, name=(unit or "Standard")[:120], sku=f"{prefix}-{uuid4().hex[:8].upper()}",
                                         selling_price=price or 0)


def rename(variant, *, name=None, price=None, group=None):
    product = variant.product
    if name is not None:
        name = " ".join(str(name).split())
        if not name:
            raise ValidationError("Enter a name.")
        product.name = name[:180]
    if group:
        product.category = category(group)
    product.save(update_fields=["name", "category", "updated_at"])
    if price is not None:
        variant.selling_price = price
        variant.save(update_fields=["selling_price", "updated_at"])
