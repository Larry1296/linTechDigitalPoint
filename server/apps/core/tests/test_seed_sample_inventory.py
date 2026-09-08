from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.models import Category, Product, ProductImage, ProductVariant, ProductVariantOptionValue
from apps.core.management.commands.seed_sample_inventory import COVERS, PADLOCKS, IDEMPOTENCY_KEY
from apps.core.models import Store
from apps.inventory.models import (
    Movement, Shelf, ShelfLevel, ShelfStack, ShelfStackCategory, StockBalance,
    StockLot, StockReceipt, StockReceiptLine, StockReceiptPlacement, Zone,
)
from apps.inventory.services import create_shelf_stack


@pytest.fixture
def racks(db):
    store = Store.objects.create(name="Sample store")
    for code in ("RIGHT", "BACKWALL"):
        zone = Zone.objects.create(store=store, code=code, name=code)
        create_shelf_stack(
            zone=zone, user=None, display_name=code, x=0, y=0, width=100, height=100, depth=30,
            level_definitions=[{"compartments": 2}, {"compartments": 2}, {"compartments": 3 if code == "RIGHT" else 2}],
        )


def seed():
    call_command("seed_sample_inventory", stdout=StringIO())


def test_seed_receives_variants_into_exact_existing_compartments(racks):
    location_ids = list(Shelf.objects.values_list("pk", flat=True))
    seed()
    assert list(Shelf.objects.values_list("pk", flat=True)) == location_ids
    assert ShelfStack.objects.count() == 2
    assert ShelfLevel.objects.count() == 6
    assert Category.objects.count() == 5
    assert Category.objects.get(slug="smartphone-covers").parent.name == "Phone Accessories"
    assert Category.objects.get(slug="padlocks").parent.name == "Electrical & Masonry Accessories"
    assert Category.objects.filter(parent=None).count() == 3
    assert Product.objects.count() == 2
    assert ProductImage.objects.count() == 2
    assert ProductVariant.objects.count() == 7
    assert ProductVariantOptionValue.objects.count() == 11
    receipt = StockReceipt.objects.get(idempotency_key=IDEMPOTENCY_KEY)
    assert receipt.status == StockReceipt.COMPLETED
    assert receipt.lines.count() == 7
    assert StockLot.objects.count() == StockBalance.objects.count() == StockReceiptPlacement.objects.count() == 7
    assert Movement.objects.count() == 7
    for sku, values, price, cost, quantity, code in (*COVERS, *PADLOCKS):
        variant = ProductVariant.objects.get(sku=sku)
        assert variant.selling_price == Decimal(price)
        assert set(variant.option_assignments.values_list("value__value", flat=True)) == set(values)
        line = receipt.lines.get(variant=variant)
        assert line.unit_cost == line.lot.unit_cost == Decimal(cost)
        assert line.received_quantity == line.lot.received_quantity == line.lot.remaining_quantity == Decimal(quantity)
        placement = line.placements.get()
        assert placement.shelf.code == code
        assert placement.balance.lot == line.lot
        assert placement.quantity == placement.balance.quantity == Decimal(quantity)
        assert variant.preferred_location.shelf == placement.shelf
        assert ShelfStackCategory.objects.filter(stack=placement.shelf.level.stack, category=variant.product.category).exists()
        movement = Movement.objects.get(lot=line.lot)
        assert movement.movement_type == "PURCHASE_RECEIPT"
        assert movement.destination == placement.shelf
        assert movement.quantity == Decimal(quantity)


def test_repeat_is_noop_even_after_stock_and_price_change(racks):
    seed()
    balance = StockBalance.objects.first()
    balance.quantity -= 1
    balance.save()
    variant = ProductVariant.objects.first()
    variant.selling_price = Decimal("999")
    variant.save()
    models = (Category, Product, ProductVariant, ProductImage, ProductVariantOptionValue,
              ShelfStackCategory, StockReceipt, StockReceiptLine, StockReceiptPlacement, StockLot, StockBalance, Movement)
    snapshots = [list(model.objects.order_by("pk").values()) for model in models]
    seed()
    seed()
    assert snapshots == [list(model.objects.order_by("pk").values()) for model in models]


@pytest.mark.parametrize("target", ["missing", "shelf", "level", "rack", "zone"])
def test_invalid_location_writes_nothing(racks, target):
    shelf = Shelf.objects.get(code="BACKWALL-R01-L02-S01")
    if target == "missing":
        shelf.history.all().delete()
        shelf.delete()
    else:
        obj = {"shelf": shelf, "level": shelf.level, "rack": shelf.level.stack, "zone": shelf.zone}[target]
        obj.active = False
        obj.save()
    with pytest.raises(CommandError, match="missing or inactive"):
        seed()
    assert not Category.objects.exists()
    assert not Product.objects.exists()
    assert not StockReceipt.objects.exists()


def test_receipt_failure_rolls_back_catalog_and_assignments(racks):
    with patch("apps.core.management.commands.seed_sample_inventory.complete_stock_receipt", side_effect=RuntimeError("failed")):
        with pytest.raises(RuntimeError, match="failed"):
            seed()
    assert not Category.objects.exists()
    assert not Product.objects.exists()
    assert not ProductImage.objects.exists()
    assert not ShelfStackCategory.objects.exists()


def test_reuses_categories_and_preserves_existing_primary_assignment(racks):
    phone = Category.objects.create(name="Phone Accessories", slug="phone-accessories")
    assignment = ShelfStackCategory.objects.create(stack=ShelfStack.objects.get(code="RIGHT-R01"), category=phone, is_primary=True)
    seed()
    assignment.refresh_from_db()
    assert assignment.is_primary
    assert Category.objects.get(slug="phone-accessories").pk == phone.pk


@pytest.mark.parametrize("name,active", [("Smartphone Covers", True), ("Old covers name", False)])
def test_adopts_existing_root_covers_and_repeat_does_not_duplicate(racks, name, active):
    category = Category.objects.create(name=name, slug="smartphone-covers", parent=None, active=active)
    assignment = ShelfStackCategory.objects.create(
        stack=ShelfStack.objects.get(code="RIGHT-R01"), category=category, is_primary=True,
    )
    seed()
    category.refresh_from_db()
    assignment.refresh_from_db()
    assert category.name == "Smartphone Covers"
    assert category.parent == Category.objects.get(slug="phone-accessories")
    assert category.active
    assert assignment.category_id == category.pk
    assert assignment.is_primary
    assert Product.objects.get(slug="sample-smartphone-cover").category_id == category.pk
    models = (Category, Product, ProductVariant, ProductImage, ShelfStackCategory,
              StockReceipt, StockReceiptLine, StockLot, StockBalance, Movement)
    snapshots = [list(model.objects.order_by("pk").values()) for model in models]
    assert [len(rows) for rows in snapshots] == [5, 2, 7, 2, 4, 1, 7, 7, 7, 7]
    seed()
    assert snapshots == [list(model.objects.order_by("pk").values()) for model in models]


def test_real_product_conflict_rolls_back_category_adoption(racks):
    category = Category.objects.create(name="Old covers", slug="smartphone-covers", active=False)
    other = Category.objects.create(name="Other", slug="other")
    product = Product.objects.create(name="Other product", slug="sample-smartphone-cover", category=other)
    with pytest.raises(CommandError, match="conflicts"):
        seed()
    category.refresh_from_db()
    product.refresh_from_db()
    assert category.name == "Old covers"
    assert category.parent is None
    assert not category.active
    assert product.category == other
    assert Category.objects.count() == 2
    assert not ShelfStackCategory.objects.exists()
    assert not StockReceipt.objects.exists()
