from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product, ProductVariant
from apps.commerce.models import SaleAllocation
from apps.core.models import Store
from apps.inventory.models import Movement, Shelf, ShelfLevel, ShelfStack, StockBalance, VariantPreferredLocation, Zone
from apps.inventory.services import (
    archive_shelf_stack,
    complete_sale,
    create_product_with_opening_stock,
    create_shelf,
    create_shelf_stack,
    receive_stock,
    reserve_stock,
    release_reservation,
    transfer_stock,
    update_shelf,
    update_shelf_stack,
)


@pytest.fixture
def data(db):
    user = User.objects.create_user("owner", password="test")
    store = Store.objects.create(name="LinTech Digital Point")
    zone = Zone.objects.create(store=store, code="LEFT", name="Left Wall", width=Decimal("300"), height=Decimal("220"))
    a = Shelf.objects.create(
        zone=zone,
        code="L-SH-0001",
        display_name="Samsung Phone Covers",
        x=5,
        y=10,
        width=80,
        height=35,
        created_by=user,
    )
    b = Shelf.objects.create(
        zone=zone,
        code="L-SH-0002",
        display_name="Chargers & Cables",
        x=100,
        y=15,
        width=115,
        height=55,
        created_by=user,
    )
    cat = Category.objects.create(name="Phone Covers", slug="phone-covers")
    product = Product.objects.create(name="Samsung Galaxy A05 Cover", slug="samsung-a05-cover", category=cat)
    variant = ProductVariant.objects.create(product=product, name="Black", sku="A05-BLK", selling_price=250)
    return user, a, b, variant


@pytest.mark.django_db
def test_dynamic_shelves_and_multiple_locations(data):
    user, a, b, v = data
    assert a.width != b.width and a.height != b.height
    lot = receive_stock(
        variant=v,
        placements=[{"shelf": a, "quantity": 6}, {"shelf": b, "quantity": 4}],
        unit_cost=120,
        reference="PO-1",
        user=user,
    )
    assert lot.unit_cost == 120 and sum(x.quantity for x in StockBalance.objects.all()) == 10


@pytest.mark.django_db
def test_receiving_generates_audit_reference_when_supplier_reference_is_blank(data):
    user, shelf, _, variant = data
    lot = receive_stock(
        variant=variant,
        placements=[{"shelf": shelf, "quantity": 2}],
        unit_cost=120,
        reference="",
        user=user,
    )
    assert lot.reference.startswith("RCV-")
    assert Movement.objects.get(lot=lot).reference == lot.reference
    assert StockBalance.objects.get(lot=lot).shelf == shelf


@pytest.mark.django_db
def test_batches_fifo_sale_and_profit(data):
    user, a, b, v = data
    first = receive_stock(
        variant=v,
        placements=[{"shelf": a, "quantity": 6}, {"shelf": b, "quantity": 4}],
        unit_cost=120,
        reference="PO-1",
        user=user,
    )
    second = receive_stock(
        variant=v, placements=[{"shelf": b, "quantity": 5}], unit_cost=140, reference="PO-2", user=user
    )
    sale = complete_sale(lines=[{"variant": v, "quantity": 7}], channel="POS", number="LT-0001", user=user)
    assert sale.cogs == Decimal("840.00000")
    assert sale.gross_profit == Decimal("910.00000")
    assert SaleAllocation.objects.filter(item__sale=sale, lot=first).count() > 0
    assert first.received_quantity == 10 and second.unit_cost == 140
    assert sum(x.quantity for x in StockBalance.objects.all()) == 8


@pytest.mark.django_db
def test_transfer_conserves_total(data):
    user, a, b, v = data
    receive_stock(variant=v, placements=[{"shelf": a, "quantity": 10}], unit_cost=120, reference="PO", user=user)
    transfer_stock(variant=v, source=a, destination=b, quantity=4, reference="TX", user=user)
    assert sum(x.quantity for x in StockBalance.objects.all()) == 10
    assert StockBalance.objects.get(shelf=b).quantity == 4


@pytest.mark.django_db
def test_reservation_release_and_oversell(data):
    user, a, b, v = data
    receive_stock(variant=v, placements=[{"shelf": a, "quantity": 5}], unit_cost=120, reference="PO", user=user)
    reservation = reserve_stock(
        variant=v, quantity=3, reference="WEB-1", expires_at=timezone.now() + timezone.timedelta(minutes=30), user=user
    )
    assert StockBalance.objects.get().reserved == 3
    with pytest.raises(ValidationError):
        reserve_stock(variant=v, quantity=3, reference="WEB-2", expires_at=timezone.now())
    release_reservation(reservation, user)
    assert StockBalance.objects.get().reserved == 0


@pytest.mark.django_db
def test_service_sale_has_no_inventory(data):
    user, a, b, v = data
    v.product.product_type = "SERVICE"
    v.product.save()
    v.service_cost = Decimal("10")
    v.save()
    sale = complete_sale(lines=[{"variant": v, "quantity": 2}], channel="POS", number="LT-SVC", user=user)
    assert sale.cogs == 20 and not StockBalance.objects.exists()


@pytest.mark.django_db
def test_shelf_code_is_collision_safe_and_history_preserves_identity(data):
    user, a, b, v = data
    zone = a.zone
    zone.next_shelf_number = 1
    zone.save()
    shelf = create_shelf(zone=zone, user=user, display_name="New shelf", x=4, y=8, width=47, height=19)
    assert shelf.code == "L-SH-0003"
    original = shelf.code
    update_shelf(shelf=shelf, user=user, display_name="Repurposed shelf")
    shelf.refresh_from_db()
    assert shelf.code == original
    assert list(shelf.history.values_list("event", flat=True)) == ["CREATED", "RENAMED"]


@pytest.mark.django_db
def test_stack_creation_builds_unequal_levels_and_permanent_codes(data):
    user, a, b, v = data
    stack = create_shelf_stack(
        zone=a.zone,
        user=user,
        display_name="Phone Accessories Rack",
        x=20,
        y=0,
        width=180,
        height=210,
        depth=40,
        level_definitions=[{"compartments": 2}, {"compartments": 2}, {"compartments": 3}, {"compartments": 3}],
    )
    assert stack.code == "LEFT-R01" and stack.number_of_levels == 4
    assert (
        ShelfLevel.objects.filter(stack=stack).count() == 4 and Shelf.objects.filter(level__stack=stack).count() == 10
    )
    assert list(stack.levels.values_list("shelves__position_in_level", flat=True)).count(3) == 2
    original = stack.code
    update_shelf_stack(stack=stack, user=user, display_name="Renamed Rack", x=25)
    stack.refresh_from_db()
    assert stack.code == original
    shelf = Shelf.objects.filter(level__stack=stack).first()
    shelf_code = shelf.code
    update_shelf(shelf=shelf, user=user, display_name="Phone Covers", width=70)
    shelf.refresh_from_db()
    assert shelf.code == shelf_code


@pytest.mark.django_db
def test_product_preference_opening_stock_and_multiple_locations(data):
    user, a, b, v = data
    stack = create_shelf_stack(
        zone=a.zone,
        user=user,
        display_name="Rack",
        x=0,
        y=0,
        width=180,
        height=200,
        depth=35,
        level_definitions=[{"compartments": 2}],
    )
    shelves = list(Shelf.objects.filter(level__stack=stack).order_by("position_in_level"))
    category = Category.objects.create(name="Chargers", slug="chargers")
    product, variant = create_product_with_opening_stock(
        user=user,
        product_data={"name": "Type-C Cable", "category": category},
        variant_data={"name": "Standard", "sku": "TYPE-C-NEW", "selling_price": 300},
        preferred_shelf=shelves[0],
        opening_quantity=10,
        opening_unit_cost=120,
    )
    assert VariantPreferredLocation.objects.get(variant=variant).shelf == shelves[0]
    assert StockBalance.objects.get(lot__variant=variant, shelf=shelves[0]).quantity == 10
    assert Movement.objects.get(variant=variant).movement_type == "OPENING_STOCK"
    receive_stock(
        variant=variant, placements=[{"shelf": shelves[1], "quantity": 5}], unit_cost=125, reference="PO-2", user=user
    )
    assert StockBalance.objects.filter(lot__variant=variant, shelf__in=shelves).count() == 2
    _, zero = create_product_with_opening_stock(
        user=user,
        product_data={"name": "Zero Cable", "category": category},
        variant_data={"name": "Standard", "sku": "ZERO-CABLE", "selling_price": 200},
        preferred_shelf=shelves[1],
        opening_quantity=0,
    )
    assert zero.preferred_location.shelf == shelves[1] and not StockBalance.objects.filter(lot__variant=zero).exists()


@pytest.mark.django_db
def test_stack_with_stock_cannot_be_archived(data):
    user, a, b, v = data
    stack = create_shelf_stack(
        zone=a.zone,
        user=user,
        display_name="Stock Rack",
        x=0,
        y=0,
        width=100,
        height=100,
        depth=30,
        level_definitions=[{"compartments": 1}],
    )
    shelf = Shelf.objects.get(level__stack=stack)
    receive_stock(variant=v, placements=[{"shelf": shelf, "quantity": 1}], unit_cost=1, reference="PO", user=user)
    with pytest.raises(ValidationError, match="still contains stock"):
        archive_shelf_stack(stack=stack, user=user)


@pytest.mark.django_db
def test_empty_stack_can_move_between_areas_and_be_archived(data):
    user, a, _, _ = data
    destination = Zone.objects.create(store=a.zone.store, code="WINDOW", name="Window", width=24, height=10)
    stack = create_shelf_stack(zone=a.zone, user=user, display_name="Movable Rack", x=1, y=1, width=6, height=7, depth=1.5, level_definitions=[{"compartments": 2}])
    permanent_code = stack.code
    update_shelf_stack(stack=stack, user=user, zone=destination, x=4, y=2, rotation=90)
    stack.refresh_from_db()
    assert stack.zone == destination and stack.x == 4 and stack.code == permanent_code
    assert not Shelf.objects.filter(level__stack=stack).exclude(zone=destination).exists()
    archive_shelf_stack(stack=stack, user=user)
    stack.refresh_from_db()
    assert not stack.active and not Shelf.objects.filter(level__stack=stack, active=True).exists()


@pytest.mark.django_db
def test_acceptance_stack_and_product_round_trip():
    owner = User.objects.create_superuser("rack-owner", "rack@example.test", "Strong-pass-1296")
    store = Store.objects.create(name="LinTech Digital Point")
    zone = Zone.objects.create(store=store, code="RIGHT", name="Right Wall", width=500, height=250)
    category = Category.objects.create(name="Phone Accessories", slug="phone-accessories")
    client = APIClient()
    client.force_authenticate(owner)
    response = client.post(
        "/api/v1/locations/stacks/",
        {
            "zone": zone.id,
            "display_name": "Phone Accessories Rack",
            "width": "180",
            "height": "210",
            "depth": "40",
            "x": "20",
            "y": "0",
            "levels": [{"compartments": 2}, {"compartments": 2}, {"compartments": 3}, {"compartments": 3}],
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["code"] == "RIGHT-R01"
    assert sum(len(level["shelves"]) for level in response.json()["levels"]) == 10
    shelf = Shelf.objects.get(code="RIGHT-R01-L03-S02")
    created = client.post(
        "/api/v1/catalog/products/create-with-stock/",
        {
            "name": "Samsung Galaxy A05 Cover",
            "category_id": category.id,
            "product_type": "STOCK_ITEM",
            "variant_name": "Black",
            "sku": "A05-BLK-ACCEPTANCE",
            "selling_price": "250",
            "preferred_shelf_id": shelf.id,
            "opening_unit_cost": "120",
            "opening_quantity": "10",
        },
        format="json",
    )
    assert created.status_code == 201
    contents = client.get(f"/api/v1/locations/shelves/{shelf.id}/contents/")
    assert contents.status_code == 200
    assert contents.json()["items"][0]["product"] == "Samsung Galaxy A05 Cover"
    assert contents.json()["items"][0]["quantity"] == 10.0
    reloaded = client.get(f"/api/v1/locations/stacks/{response.json()['id']}/")
    assert reloaded.status_code == 200
    assert reloaded.json()["width"] == "180.00"
    assert len(reloaded.json()["levels"]) == 4


@pytest.mark.django_db
def test_owner_defines_any_shop_area_without_seeded_zone_choices():
    owner = User.objects.create_superuser("area-owner", "area@example.test", "Strong-pass-1296")
    client = APIClient()
    client.force_authenticate(owner)
    response = client.post(
        "/api/v1/locations/zones/", {"name": "Upstairs Window Display", "width": 24, "height": 10.5}, format="json"
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Upstairs Window Display"
    assert response.json()["code"] == "UPSTAIRSWINDOWDI"
    assert response.json()["width"] == "24.00"
    assert response.json()["height"] == "10.50"
    assert Store.objects.get().measurement_unit == "ft"
