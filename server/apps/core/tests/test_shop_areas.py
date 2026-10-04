"""Shop areas can be renamed, resized and removed without losing rack or stock history."""
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.models import Shelf, Zone
from apps.inventory.services import archive_shelf_stack, create_shelf_stack, receive_stock


@pytest.fixture
def owner(db):
    client = APIClient()
    user = User.objects.create(username="owner", is_staff=True, is_superuser=True)
    client.force_authenticate(user)
    Store.objects.create(name="Main branch")
    return client, user


def area(name, code):
    return Zone.objects.create(store=Store.objects.get(), name=name, code=code)


def rack(zone, user, name):
    return create_shelf_stack(zone=zone, user=user, display_name=name, x=0, y=0, width=100, height=100, depth=30,
                              level_definitions=[{"compartments": 1}])


def test_area_name_and_size_can_be_edited(owner):
    client, _ = owner
    zone = area("Left Wal", "LEFTWALL")
    response = client.patch(f"/api/v1/locations/zones/{zone.pk}/", {"name": " Left Wall ", "width": "12", "height": "4"}, format="json")
    assert response.status_code == 200, response.content
    zone.refresh_from_db()
    assert (zone.name, zone.width, zone.height, zone.code) == ("Left Wall", 12, 4, "LEFTWALL")
    assert client.patch(f"/api/v1/locations/zones/{zone.pk}/", {"name": " "}, format="json").status_code == 400
    assert client.patch(f"/api/v1/locations/zones/{zone.pk}/", {"width": "0"}, format="json").status_code == 400


def test_never_used_area_is_deleted_and_area_with_removed_racks_is_hidden(owner):
    client, user = owner
    empty = area("Spare corner", "SPARE")
    old = area("Left Wall", "LEFTWALL2")
    archive_shelf_stack(stack=rack(old, user, "Computer Accessories Rack"), user=user)
    assert client.delete(f"/api/v1/locations/zones/{empty.pk}/").status_code == 204
    assert not Zone.objects.filter(pk=empty.pk).exists()
    assert client.delete(f"/api/v1/locations/zones/{old.pk}/").status_code == 204
    old.refresh_from_db()
    assert old.active is False
    assert [row["id"] for row in client.get("/api/v1/locations/zones/").json()] == []


def test_area_with_active_rack_or_stock_explains_why_it_stays(owner):
    client, user = owner
    wall = area("Right Wall", "RIGHTWALL")
    rack(wall, user, "Computer Accessories")
    response = client.delete(f"/api/v1/locations/zones/{wall.pk}/")
    assert response.status_code == 400
    assert response.json()["detail"] == ("Right Wall still has 1 rack: Computer Accessories. "
                                         "Remove them or move them to another area first.")

    floor = area("Floor", "FLOOR")
    shelf = Shelf.objects.create(zone=floor, code="F1", display_name="Crate", x=0, y=0, width=10, height=10)
    category = Category.objects.create(name="Cables", slug="cables")
    variant = ProductVariant.objects.create(product=Product.objects.create(name="USB cable", slug="usb", category=category),
                                            sku="USB-1", selling_price=100)
    receive_stock(variant=variant, placements=[{"shelf": shelf, "quantity": 2}], unit_cost=50, reference="R1", user=user)
    response = client.delete(f"/api/v1/locations/zones/{floor.pk}/")
    assert response.status_code == 400 and "still holds stock" in response.json()["detail"]
    assert Zone.objects.filter(pk__in=[wall.pk, floor.pk], active=True).count() == 2
