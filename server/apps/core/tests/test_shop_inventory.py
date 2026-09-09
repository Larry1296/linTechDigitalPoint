from decimal import Decimal
from io import StringIO
from unittest.mock import patch
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from apps.core.models import Store
from apps.core.shop_stock import ROUNDS
from apps.catalog.models import Category, Product, ProductVariant
from apps.inventory.models import Shelf, StockReceipt, StockLot, StockBalance, Movement, StockReceiptPlacement
from apps.inventory.models import Zone
from apps.inventory.services import create_shelf_stack


@pytest.fixture
def racks(db):
    store = Store.objects.create(name="Sample store")
    for code in ("RIGHT", "BACKWALL"):
        zone = Zone.objects.create(store=store, code=code, name=code)
        create_shelf_stack(
            zone=zone,
            user=None,
            display_name=code,
            x=0,
            y=0,
            width=100,
            height=100,
            depth=30,
            level_definitions=[{"compartments": 2}, {"compartments": 2}, {"compartments": 3 if code == "RIGHT" else 2}],
        )


def run(command, **kwargs):
    output = StringIO()
    call_command(command, stdout=output, **kwargs)
    return output.getvalue()


@pytest.fixture
def shop(db):
    Store.objects.create(name="linTech Digital Point")
    run("setup_shop_layout")


def test_layout_repeat_and_conflict(shop):
    before = list(Shelf.objects.values())
    run("setup_shop_layout")
    assert before == list(Shelf.objects.values())
    assert set(Shelf.objects.values_list("physical_label", flat=True)) == {
        f"AL{i}C{j}S1" for i in (1, 2, 3) for j in (1, 2)
    }
    Shelf.objects.filter(physical_label="AL1C1S1").update(physical_label="WRONG")
    with pytest.raises(CommandError):
        run("setup_shop_layout")


def test_receive_repeat_and_increment(shop):
    from django.apps import apps

    models = [model for model in apps.get_models() if model._meta.managed]
    before_dry_run = [list(model.objects.order_by("pk").values()) for model in models]
    output = run("seed_shop_inventory", dry_run=True)
    assert "14 lines, 18 units, KSh 5,190" in output
    assert "6 locations valid" in output
    assert "no records committed" in output
    assert before_dry_run == [list(model.objects.order_by("pk").values()) for model in models]
    assert not Product.objects.exists()
    run("seed_shop_inventory")
    receipt = StockReceipt.objects.get()
    assert receipt.lines.count() == 14
    assert sum(l.received_quantity for l in receipt.lines.all()) == 18
    assert sum(l.received_quantity * l.unit_cost for l in receipt.lines.all()) == Decimal("5190")
    assert not Product.objects.filter(ecommerce_visible=True).exists()
    assert not Product.objects.filter(online_orderable=True).exists()
    assert not ProductVariant.objects.exclude(selling_price=0).exists()
    for line in receipt.lines.all():
        placement = line.placements.get()
        assert placement.balance.quantity == line.received_quantity == line.lot.remaining_quantity
        assert placement.balance.lot == line.lot
        assert line.lot.unit_cost == line.unit_cost
        movement = Movement.objects.get(lot=line.lot)
        assert movement.movement_type == "PURCHASE_RECEIPT"
        assert movement.destination == placement.shelf
    models = (StockReceipt, StockLot, StockBalance, Movement, StockReceiptPlacement, ProductVariant)
    before = [list(m.objects.values()) for m in models]
    run("seed_shop_inventory")
    assert before == [list(m.objects.values()) for m in models]
    later = {
        **ROUNDS[0],
        "key": "test-round-2",
        "reference": "148",
        "lines": (ROUNDS[0]["lines"][0],),
        "expected_lines": 1,
        "expected_quantity": 2,
        "expected_cost": "320",
    }
    with patch("apps.core.management.commands.seed_shop_inventory.ROUNDS", (*ROUNDS, later)):
        run("seed_shop_inventory")
        run("seed_shop_inventory")
    assert StockReceipt.objects.count() == 2
    assert StockLot.objects.count() == 15
    assert StockReceipt.objects.get(pk=receipt.pk).lines.count() == 14


@pytest.mark.parametrize("target", ["missing", "shelf", "level", "rack", "zone", "category"])
def test_round_location_rollback(shop, target):
    shelf = Shelf.objects.get(physical_label="AL3C2S1")
    if target == "missing":
        shelf.history.all().delete()
        shelf.delete()
    else:
        obj = {
            "shelf": shelf,
            "level": shelf.level,
            "rack": shelf.level.stack,
            "zone": shelf.zone,
            "category": Category.objects.get(slug="mobile-accessories"),
        }[target]
        obj.active = False
        obj.save()
    with pytest.raises(CommandError):
        run("seed_shop_inventory")
    assert not Product.objects.exists()
    assert not StockReceipt.objects.exists()


def test_cleanup_preserves_genuine_and_preview(racks):
    run("seed_sample_inventory")
    category = Category.objects.get(slug="smartphone-covers")
    genuine = Product.objects.create(name="Genuine", slug="genuine", category=category)
    run("cleanup_sample_inventory")
    assert StockReceipt.objects.count() == 1
    run("cleanup_sample_inventory", execute=True)
    assert Product.objects.get() == genuine
    assert Category.objects.filter(pk=category.pk).exists()
    assert not StockReceipt.objects.exists()
    assert not StockLot.objects.exists()
    assert not Movement.objects.exists()


@pytest.mark.parametrize("conflict", ["balance", "movement", "cart"])
def test_cleanup_refuses_conflicts(racks, conflict):
    run("seed_sample_inventory")
    balance = StockBalance.objects.first()
    if conflict == "balance":
        balance.quantity -= 1
        balance.save()
    elif conflict == "movement":
        Movement.objects.create(
            variant=balance.lot.variant, lot=balance.lot, quantity=1, movement_type="SALE", reference="REAL"
        )
    else:
        from apps.commerce.models import Cart, CartItem

        CartItem.objects.create(cart=Cart.objects.create(), variant=balance.lot.variant, quantity=1)
    before = list(StockBalance.objects.values())
    with pytest.raises(CommandError):
        run("cleanup_sample_inventory", execute=True)
    assert before == list(StockBalance.objects.values())
    assert StockReceipt.objects.count() == 1


def test_unreconciled_manifest_rejected(shop):
    from django.apps import apps

    models = [model for model in apps.get_models() if model._meta.managed]
    before = [list(model.objects.order_by("pk").values()) for model in models]
    with patch("apps.core.management.commands.seed_shop_inventory.ROUNDS", ({**ROUNDS[0], "expected_quantity": 19},)):
        with pytest.raises(CommandError, match="Source totals disagree"):
            run("seed_shop_inventory")
    assert not StockReceipt.objects.exists()
    assert not Product.objects.exists()
    assert before == [list(model.objects.order_by("pk").values()) for model in models]


def test_public_catalog_hides_opening_stock_and_internal_fields(shop):
    from rest_framework.test import APIClient

    run("seed_shop_inventory")
    client = APIClient()
    response = client.get("/api/v1/store/products/")
    assert response.status_code == 200
    assert response.data == []
    from apps.core.api import PublicVariantSerializer

    serialized = str(PublicVariantSerializer(ProductVariant.objects.first()).data)
    for private in ("unit_cost", "latest_bp", "average_stock_cost", "shelf", "location", "AL1", "cogs"):
        assert private not in serialized
    assert client.get("/api/v1/catalog/products/").status_code in (401, 403)


@pytest.mark.parametrize("conflict", ["reservation", "extra_lot", "sale"])
def test_cleanup_preserves_business_references(racks, conflict):
    from django.utils import timezone
    from apps.inventory.models import Reservation
    from apps.commerce.models import Sale, SaleItem

    run("seed_sample_inventory")
    variant = ProductVariant.objects.first()
    if conflict == "reservation":
        Reservation.objects.create(
            variant=variant, quantity=1, active=False, status="RELEASED", reference="GENUINE", expires_at=timezone.now()
        )
    elif conflict == "extra_lot":
        StockLot.objects.create(
            variant=variant,
            reference="GENUINE",
            received_quantity=1,
            remaining_quantity=1,
            unit_cost=1,
            received_at=timezone.now(),
        )
    else:
        SaleItem.objects.create(
            sale=Sale.objects.create(number="GENUINE", channel="POS"), variant=variant, quantity=1, unit_price=10
        )
    with pytest.raises(CommandError, match="Unsafe genuine reference"):
        run("cleanup_sample_inventory", execute=True)
    assert StockReceipt.objects.count() == 1
    assert ProductVariant.objects.count() == 7


def test_guarded_empty_test_layout_removal(racks):
    run("cleanup_sample_inventory", remove_test_layout=True)
    assert Zone.objects.count() == 2
    run("cleanup_sample_inventory", remove_test_layout=True, execute=True)
    assert not Zone.objects.exists()
    assert Store.objects.count() == 1


def test_layout_removal_rejects_genuine_stock(racks):
    from apps.inventory.services import receive_stock

    product = Product.objects.create(
        name="Genuine", slug="genuine", category=Category.objects.create(name="Real", slug="real")
    )
    variant = ProductVariant.objects.create(product=product, sku="REAL")
    receive_stock(
        variant=variant, placements=[{"shelf": Shelf.objects.first(), "quantity": 1}], unit_cost=10, reference="GENUINE"
    )
    with pytest.raises(CommandError):
        run("cleanup_sample_inventory", remove_test_layout=True, execute=True)
    assert Zone.objects.count() == 2
    assert StockLot.objects.get().variant == variant


def test_round_failure_rolls_back_all_new_records(shop):
    with patch(
        "apps.core.management.commands.seed_shop_inventory.complete_stock_receipt", side_effect=RuntimeError("failed")
    ):
        with pytest.raises(RuntimeError):
            run("seed_shop_inventory")
    assert not Product.objects.exists()
    assert not StockReceipt.objects.exists()


def test_cleanup_leaves_genuine_receipt_graph_unchanged(racks):
    from apps.inventory.services import complete_stock_receipt

    run("seed_sample_inventory")
    product = Product.objects.create(
        name="Real cable", slug="real-cable", category=Category.objects.get(slug="smartphone-covers")
    )
    variant = ProductVariant.objects.create(product=product, sku="REAL-CABLE", selling_price=300)
    receipt = complete_stock_receipt(
        external_reference="GENUINE",
        idempotency_key="genuine-round",
        lines=[
            {
                "variant_id": variant.pk,
                "received_quantity": 2,
                "unit_cost": 100,
                "placements": [{"shelf_id": Shelf.objects.get(code="RIGHT-R01-L01-S01").pk, "quantity": 2}],
            }
        ],
    )
    lots = list(StockLot.objects.filter(variant=variant).values())
    movements = list(Movement.objects.filter(variant=variant).values())
    balances = list(StockBalance.objects.filter(lot__variant=variant).values())
    shelves = list(Shelf.objects.values())
    categories = list(Category.objects.values())
    run("cleanup_sample_inventory", execute=True)
    assert StockReceipt.objects.get().pk == receipt.pk
    assert lots == list(StockLot.objects.values())
    assert movements == list(Movement.objects.values())
    assert balances == list(StockBalance.objects.values())
    assert shelves == list(Shelf.objects.values())
    assert categories == list(Category.objects.values())
