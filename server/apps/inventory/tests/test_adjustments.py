from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission, User
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.adjustments import adjust_stock
from apps.inventory.models import (
    Movement,
    Shelf,
    StockAdjustment,
    StockBalance,
    StockLot,
    StockReceipt,
    StockReceiptLine,
    StockReceiptPlacement,
    Zone,
)
from apps.inventory.services import complete_sale, complete_stock_receipt, create_shelf_stack, reserve_stock
from apps.commerce.models import Sale, SaleItem, SaleAllocation, Payment


@pytest.fixture
def stock(db):
    user = User.objects.create_superuser("adjuster", "owner@example.com", "test")
    store = Store.objects.create(name="Shop")
    zone = Zone.objects.create(store=store, code="A", name="Zone A")
    stack = create_shelf_stack(
        zone=zone,
        user=user,
        display_name="Rack",
        x=0,
        y=0,
        width=100,
        height=100,
        depth=20,
        level_definitions=[{"compartments": 2, "physical_labels": ["AL1C1S1", "AL1C2S1"]}],
    )
    shelf = Shelf.objects.get(level__stack=stack, position_in_level=1)
    category = Category.objects.create(name="Mobile Accessories", slug="mobile-accessories")
    stack.category_assignments.create(category=category, is_primary=True)
    product = Product.objects.create(name="Amaya USB Charging Cable", slug="amaya", category=category)
    variant = ProductVariant.objects.create(
        product=product, name="AM-M01 — Type-B (Micro-USB) — White — 1.2m — 3.1A", sku="TYPE-B", selling_price=300
    )
    receipt = complete_stock_receipt(
        user=user,
        external_reference="147",
        lines=[
            {
                "variant_id": variant.pk,
                "received_quantity": 3,
                "unit_cost": 160,
                "placements": [{"shelf_id": shelf.pk, "quantity": 3}],
            }
        ],
    )
    complete_sale(lines=[{"variant": variant, "quantity": 1}], channel="POS", number="SALE-1", user=user)
    return user, variant, shelf, receipt.lines.get().lot


def post(stock, **changes):
    user, variant, shelf, lot = stock
    payload = dict(
        user=user,
        variant_id=variant.pk,
        shelf_id=shelf.pk,
        expected_quantity=2,
        counted_quantity=4,
        reason="Opening stock correction",
        notes="Physical recount found four Type-B cables after one earlier sale.",
        reference="COUNT-1",
        idempotency_key="count-1",
        confirmed=True,
        lot_id=lot.pk,
    )
    payload.update(changes)
    return adjust_stock(**payload)


def snapshots():
    return [
        list(model.objects.order_by("pk").values())
        for model in (StockReceipt, StockReceiptLine, StockReceiptPlacement, Sale, SaleItem, SaleAllocation, Payment)
    ]


def test_increase_preserves_receipt_sale_and_history(stock):
    before = snapshots()
    movements = list(Movement.objects.values())
    a = post(stock)
    lot = StockLot.objects.get(pk=stock[3].pk)
    assert (a.quantity_before, a.amount, a.quantity_after) == (2, 2, 4)
    assert (lot.received_quantity, lot.remaining_quantity, lot.unit_cost) == (3, 4, 160)
    assert StockBalance.objects.get(lot=lot).quantity == 4
    assert snapshots() == before
    assert list(Movement.objects.filter(pk__in=[m["id"] for m in movements]).values()) == movements
    m = a.movements.get()
    assert (m.movement_type, m.quantity_before, m.quantity, m.quantity_after, m.performed_by_id, m.destination_id) == (
        "STOCK_ADJUSTMENT",
        2,
        2,
        4,
        stock[0].pk,
        stock[2].pk,
    )
    assert post(stock).pk == a.pk
    assert StockAdjustment.objects.count() == 1
    assert Movement.objects.filter(movement_type="STOCK_ADJUSTMENT").count() == 1


def test_decrease_fifo_and_reserved_stock(stock):
    user, variant, shelf, lot = stock
    complete_stock_receipt(
        user=user,
        external_reference="148",
        lines=[
            {
                "variant_id": variant.pk,
                "received_quantity": 3,
                "unit_cost": 170,
                "placements": [{"shelf_id": shelf.pk, "quantity": 3}],
            }
        ],
    )
    reserve_stock(variant=variant, quantity=1, reference="reserve", expires_at=timezone.now(), user=user)
    a = post(stock, expected_quantity=5, counted_quantity=1, reason="Damaged item")
    assert list(a.movements.order_by("pk").values_list("quantity", flat=True)) == [Decimal(-1), Decimal(-3)]
    assert sum(StockBalance.objects.values_list("quantity", flat=True)) == 1
    assert sum(StockLot.objects.values_list("remaining_quantity", flat=True)) == 1
    assert StockBalance.objects.get(lot=lot).reserved == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"counted_quantity": -1},
        {"counted_quantity": "NaN"},
        {"counted_quantity": "1.0001"},
        {"expected_quantity": 3},
        {"counted_quantity": 2},
        {"reason": ""},
        {"confirmed": False},
        {"shelf_id": 99999},
        {"lot_id": 99999},
    ],
)
def test_rejects_invalid_without_writes(stock, changes):
    before = list(StockBalance.objects.values())
    with pytest.raises(ValidationError):
        post(stock, **changes)
    assert list(StockBalance.objects.values()) == before
    assert not StockAdjustment.objects.exists()
    assert StockLot.objects.get(pk=stock[3].pk).remaining_quantity == 2


def test_reserved_and_inactive_shelf_rejected(stock):
    reserve_stock(variant=stock[1], quantity=2, reference="hold", expires_at=timezone.now(), user=stock[0])
    with pytest.raises(ValidationError, match="reserved"):
        post(stock, counted_quantity=1)
    Shelf.objects.filter(pk=stock[2].pk).update(active=False)
    with pytest.raises(ValidationError, match="active"):
        post(stock)
    assert not StockAdjustment.objects.exists()


def test_rollback_if_movement_write_fails(stock):
    before = snapshots()
    with patch("apps.inventory.adjustments.Movement.objects.create", side_effect=RuntimeError("failed movement")):
        with pytest.raises(RuntimeError):
            post(stock)
    assert snapshots() == before
    assert not StockAdjustment.objects.exists()
    assert StockBalance.objects.get(lot=stock[3]).quantity == 2
    assert StockLot.objects.get(pk=stock[3].pk).remaining_quantity == 2


def test_new_adjustment_lot_requires_explicit_cost(stock):
    with pytest.raises(ValidationError, match="cost"):
        post(stock, lot_id=None)
    a = post(stock, lot_id=None, new_lot_unit_cost=160, reason="Found stock")
    lot = a.movements.get().lot
    assert (lot.received_quantity, lot.remaining_quantity) == (0, 2)
    assert StockReceipt.objects.count() == 1


def test_permissions_api_audit_and_read_only(stock):
    client = APIClient()
    url = "/api/v1/inventory/adjustments/"
    assert client.get(url).status_code == 403
    staff = User.objects.create_user("cashier", is_staff=True)
    client.force_authenticate(staff)
    assert client.get(url).status_code == 403
    with pytest.raises(PermissionDenied):
        post(stock, user=staff)
    staff.user_permissions.add(Permission.objects.get(codename="adjust_stock", content_type__app_label="inventory"))
    staff = User.objects.get(pk=staff.pk)
    client.force_authenticate(staff)
    a = post(stock, user=staff)
    data = client.get(url).json()[0]
    assert (data["id"], data["administrator"], data["shelf"], data["reason"]) == (
        a.pk,
        "cashier",
        "AL1C1S1",
        "Opening stock correction",
    )
    history = client.get(f"{url}variants/{stock[1].pk}/").json()["history"]
    assert history[0]["adjustment_id"] == a.pk
    assert "Type-B" in data["display_name"]
    assert client.patch(url, {}).status_code == 405
    assert client.delete(url).status_code == 405
    assert client.post(url, {"counted_quantity": -1}, format="json").status_code == 400


def test_database_rejects_adjustment_or_movement_mutation(stock):
    a = post(stock)
    for queryset in (StockAdjustment.objects.filter(pk=a.pk), Movement.objects.filter(adjustment=a)):
        with pytest.raises(DatabaseError), transaction.atomic():
            queryset.update(notes="rewrite")
    with pytest.raises(DatabaseError), transaction.atomic():
        Movement.objects.filter(adjustment=a).delete()
    with pytest.raises(ValidationError, match="different"):
        post(stock, counted_quantity=5)


def test_api_post_and_public_stock_without_audit_leak(stock):
    client = APIClient()
    client.force_authenticate(stock[0])
    payload = {
        "variant_id": stock[1].pk,
        "shelf_id": stock[2].pk,
        "expected_quantity": "2",
        "counted_quantity": "4",
        "reason": "Opening stock correction",
        "confirmed": True,
        "lot_id": stock[3].pk,
        "idempotency_key": "api-count",
    }
    response = client.post("/api/v1/inventory/adjustments/", payload, format="json")
    assert response.status_code == 200
    assert Decimal(str(response.data["amount"])) == 2
    assert client.post("/api/v1/inventory/adjustments/", payload, format="json").data["id"] == response.data["id"]
    client.force_authenticate(None)
    response = client.get(f"/api/v1/store/products/{stock[1].pk}/")
    assert response.status_code == 200
    assert Decimal(str(response.data["available"])) == 4
    assert not set(response.data) & {"unit_cost", "lots", "locations", "shelf", "adjustments", "history"}
    assert client.get(f"/api/v1/inventory/adjustments/variants/{stock[1].pk}/").status_code == 403


def test_decrease_to_zero_and_other_compartment_untouched(stock):
    user, variant, shelf, lot = stock
    other = Shelf.objects.exclude(pk=shelf.pk).get()
    complete_stock_receipt(
        user=user,
        external_reference="OTHER",
        lines=[
            {
                "variant_id": variant.pk,
                "received_quantity": 5,
                "unit_cost": 160,
                "placements": [{"shelf_id": other.pk, "quantity": 5}],
            }
        ],
    )
    other_before = list(StockBalance.objects.filter(shelf=other).values())
    a = post(stock, counted_quantity=0, reason="Lost item")
    assert a.amount == -2
    assert StockBalance.objects.get(lot=lot).quantity == 0
    assert StockLot.objects.get(pk=lot.pk).remaining_quantity == 0
    assert list(StockBalance.objects.filter(shelf=other).values()) == other_before


@pytest.mark.parametrize("target", ["zone", "level", "rack"])
def test_inactive_hierarchy_rejected(stock, target):
    shelf = stock[2]
    obj = {"zone": shelf.zone, "level": shelf.level, "rack": shelf.level.stack}[target]
    obj.active = False
    obj.save()
    with pytest.raises(ValidationError, match="active"):
        post(stock)
    assert not StockAdjustment.objects.exists()
