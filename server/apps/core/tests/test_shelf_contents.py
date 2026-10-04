"""Opening a shelf shows every item on it once, where the shelf is, and costs only to those allowed."""
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.models import Shelf, ShelfStackCategory, Zone
from apps.inventory.services import create_shelf_stack, receive_stock


@pytest.fixture
def shelf(db):
    owner = User.objects.create(username="owner", is_staff=True, is_superuser=True)
    zone = Zone.objects.create(store=Store.objects.create(name="Main branch"), code="LEFTWALL", name="Left Wall")
    category = Category.objects.create(name="Mobile Accessories", slug="mobile-accessories")
    rack = create_shelf_stack(zone=zone, user=owner, display_name="Phone Accessories Rack", x=0, y=0, width=6,
                              height=7, depth=1.5, level_definitions=[{"compartments": 2}, {"compartments": 3}])
    ShelfStackCategory.objects.create(stack=rack, category=category, is_primary=True)
    target = Shelf.objects.get(level__stack=rack, level__level_number=2, position_in_level=1)
    charger = ProductVariant.objects.create(sku="CHG-25W", selling_price=600, name="25W",
        product=Product.objects.create(name="Type-C charger", slug="charger", category=category))
    cover = ProductVariant.objects.create(sku="COV-C22", selling_price=300, name="Camon 22",
        product=Product.objects.create(name="Phone cover", slug="cover", category=category))
    receive_stock(variant=charger, placements=[{"shelf": target, "quantity": 4}], unit_cost=350, reference="INV-1", user=owner)
    receive_stock(variant=charger, placements=[{"shelf": target, "quantity": 6}], unit_cost=370, reference="INV-2", user=owner)
    receive_stock(variant=cover, placements=[{"shelf": target, "quantity": 20}], unit_cost=120, reference="INV-3", user=owner)
    return owner, target


def test_owner_sees_each_item_once_with_location_totals_and_costs(shelf):
    owner, target = shelf
    client = APIClient()
    client.force_authenticate(owner)
    data = client.get(f"/api/v1/locations/shelves/{target.pk}/contents/").json()
    assert data["location"] == {"area": "Left Wall", "rack": "Phone Accessories Rack", "rack_code": "LEFTWALL-R01",
                                "level": 2, "position": 1, "categories": ["Mobile Accessories"]}
    cover, charger = data["items"]  # Alphabetical, as a shelf label would list them.
    assert (charger["product"], charger["sku"], charger["category"]) == ("Type-C charger", "CHG-25W", "Mobile Accessories")
    assert Decimal(charger["quantity"]) == 10 and charger["batches"] == 2 and Decimal(charger["available"]) == 10
    assert Decimal(charger["cost_value"]) == 4 * 350 + 6 * 370 and Decimal(charger["retail_value"]) == 6000
    assert Decimal(cover["quantity"]) == 20
    assert data["totals"]["items"] == 2 and Decimal(data["totals"]["units"]) == 30
    assert Decimal(data["totals"]["retail_value"]) == 12000 and Decimal(data["totals"]["cost_value"]) == 6020
    assert data["show_cost"] is True
    assert {m["direction"] for m in data["recent_movements"]} == {"in"}


def test_staff_without_profit_access_never_receive_buying_costs(shelf):
    _, target = shelf
    clerk = User.objects.create(username="clerk", is_staff=True)
    client = APIClient()
    client.force_authenticate(clerk)
    response = client.get(f"/api/v1/locations/shelves/{target.pk}/contents/")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["show_cost"] is False and "cost_value" not in data["totals"]
    assert all("cost_value" not in item for item in data["items"])
    assert Decimal(data["totals"]["retail_value"]) == 12000
