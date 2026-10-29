"""The eatery's menu and kitchen (see models.py)."""
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import StockBalance

from .catalog import new_variant, rename
from .models import KitchenIngredient, KitchenUse, KitchenUseLine, MenuItem

KITCHEN_GROUP = "Kitchen stock"


@transaction.atomic
def add_item(*, name, price, group="Menu"):
    if Decimal(str(price or 0)) < 0:
        raise ValidationError("A price cannot be negative.")
    variant = new_variant(name=name, kind=Product.SERVICE, group=group or "Menu", price=price, prefix="MENU")
    return MenuItem.objects.create(variant=variant)


@transaction.atomic
def change_item(item, *, name=None, price=None, group=None, available=None, active=None):
    if price is not None and Decimal(str(price)) < 0:
        raise ValidationError("A price cannot be negative.")
    rename(item.variant, name=name, price=price, group=group)
    if available is not None:
        item.available = bool(available)
        item.save(update_fields=["available", "updated_at"])
    if active is not None:
        # Off the menu for good: kept for its past sales.
        Product.objects.filter(pk=item.variant.product_id).update(active=bool(active), updated_at=timezone.now())
    return item


def in_store(variant):
    """How much of an ingredient the books show in this branch's store, free to use."""
    return StockBalance.objects.filter(lot__variant=variant).aggregate(v=Sum(F("quantity") - F("reserved")))["v"] or Decimal("0")


@transaction.atomic
def add_ingredient(*, name=None, unit="", variant_id=None, sold_at_till=False):
    """A new kitchen ingredient, or stock already in the catalogue (cooking oil the shop also sells) used in the kitchen."""
    if variant_id:
        variant = ProductVariant.objects.select_related("product").filter(pk=variant_id, product__product_type=Product.STOCK_ITEM).first()
        if not variant:
            raise ValidationError("Choose a stock item.")
        found = KitchenIngredient.objects.filter(variant=variant).first()
        return found or KitchenIngredient.objects.create(variant=variant, sold_at_till=True if sold_at_till is None else sold_at_till)
    variant = new_variant(name=name, kind=Product.STOCK_ITEM, group=KITCHEN_GROUP, unit=" ".join(str(unit or "").split()) or "Standard",
                          prefix="KIT")
    return KitchenIngredient.objects.create(variant=variant, sold_at_till=bool(sold_at_till))


def _quantity(value, label):
    try:
        number = Decimal(str(value))
    except Exception:
        raise ValidationError(f"Enter {label} as a number.")
    if not number.is_finite() or number < 0:
        raise ValidationError(f"Enter {label} as a number, zero or more.")
    return number


@transaction.atomic
def record_use(*, user, way, lines, used_on=None, note=""):
    """What the kitchen used, at what it cost to buy (oldest stock first). ``way``: USED, each line's ``quantity`` used;
    or COUNTED, each line's ``left`` as counted, and used is what the books show less what is left. Its cost is the cost
    of the meals sold (Dr food used in the kitchen, Cr stock)."""
    from apps.accounting.ledger import paired, post_journal
    from apps.inventory.services import consume_stock_fifo
    from apps.tenancy.transactions import lock_business
    lock_business()
    if way not in (KitchenUse.USED, KitchenUse.COUNTED):
        raise ValidationError("Say whether you are entering what was used or what is left.")
    used_on = used_on or timezone.localdate()
    if used_on > timezone.localdate():
        raise ValidationError("Kitchen use cannot be dated ahead of today.")
    rows = []
    for raw in lines or []:
        ingredient = KitchenIngredient.objects.select_related("variant__product").filter(pk=raw.get("ingredient_id")).first()
        if not ingredient:
            raise ValidationError("Choose a kitchen ingredient.")
        variant, store = ingredient.variant, in_store(ingredient.variant)
        if way == KitchenUse.USED:
            if raw.get("quantity") in (None, ""):
                continue
            used, left = _quantity(raw.get("quantity"), "the amount used"), None
        else:
            if raw.get("left") in (None, ""):
                continue
            left = _quantity(raw.get("left"), "what is left")
            if left > store:
                raise ValidationError(f"{variant.product.name}: you counted {left:g} but the books show only {store:g}. "
                                      "Record the stock that came in (Receive stock) first, then count again.")
            used = store - left
        if used > store:
            raise ValidationError(f"{variant.product.name}: only {store:g} is in the store, so {used:g} cannot have been used. "
                                  "Record the stock that came in (Receive stock) first.")
        if used > 0:
            rows.append((variant, used, left))
    if not rows:
        raise ValidationError("Nothing was used: enter at least one amount.")
    use = KitchenUse.objects.create(number=f"KIT-{used_on:%y%m%d}-{uuid4().hex[:5].upper()}", used_on=used_on, way=way,
                                    note=str(note or "")[:255], recorded_by=user)
    total = Decimal("0")
    for variant, used, left in rows:
        cost = consume_stock_fifo(variant=variant, quantity=used, reference=use.number, movement_type="KITCHEN_USE", user=user)
        cost = Decimal(cost).quantize(Decimal("0.01"))
        KitchenUseLine.objects.create(use=use, variant=variant, quantity=used, left=left, cost=cost)
        total += cost
    use.total_cost = total
    use.save(update_fields=["total_cost", "updated_at"])
    if total:
        post_journal(key=f"kitchen:{use.pk}", description=f"Food used in the kitchen {use.number}", lines=paired("5020", "1200", total),
                     date=used_on, user=user)
    return use
