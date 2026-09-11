from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.catalog.models import ProductVariant
from apps.commerce.models import SaleAllocation
from apps.inventory.models import Movement, StockBalance, StockLot, StockReceiptLineCorrection
from apps.inventory.receipt_corrections import correct_receipt_line
from apps.inventory.services import complete_sale, complete_stock_receipt, reserve_stock, transfer_stock
from test_receipts import receipt_data

REASON = "Amaya 10W wall-charger buying price was mistakenly entered against the cable."


@pytest.fixture
def receipt_line(receipt_data):
    user, variant, shelves = receipt_data
    user.is_staff = True
    user.save()
    user.user_permissions.add(Permission.objects.get(codename="change_stockreceipt"))
    variant.product.name = "Amaya charging cable"
    variant.product.save()
    receipt = complete_stock_receipt(user=user, external_reference="145", lines=[{
        "variant_id": variant.pk, "received_quantity": "3", "unit_cost": "160",
        "placements": [{"shelf_id": shelves[0].pk, "quantity": "3"}],
    }])
    return user, receipt.lines.get(), shelves


def correct(stock, **changes):
    user, line, _ = stock
    data = {"variant_id": line.variant_id, "unit_cost": "80.00", "received_quantity": "3.000",
            "reason": REASON, "confirmed": True, "expected_updated_at": line.updated_at.isoformat()}
    data.update(changes)
    return correct_receipt_line(receipt_id=line.receipt_id, line_id=line.pk, user=user, data=data)


def test_cost_correction_atomic_and_no_stock_changes(receipt_line):
    _, original, _ = receipt_line
    balances = list(StockBalance.objects.values())
    movements = list(Movement.objects.values())
    placements = list(original.placements.values())
    result = correct(receipt_line)
    lot = StockLot.objects.get(pk=result.lot_id)
    assert result.unit_cost == lot.unit_cost == Decimal("80")
    assert result.received_quantity * result.unit_cost == 240
    assert lot.received_quantity == lot.remaining_quantity == result.received_quantity == 3
    assert list(StockBalance.objects.values()) == balances
    assert list(Movement.objects.values()) == movements
    assert list(original.placements.values()) == placements
    audit = result.corrections.get()
    assert audit.reason == REASON and audit.performed_by == receipt_line[0]
    assert Decimal(audit.before["unit_cost"]) == 160
    assert Decimal(audit.after["unit_cost"]) == 80
    assert Decimal(audit.after["line_total"]) == 240


def test_future_cogs_uses_corrected_cost_and_historical_cogs_stays_fixed(receipt_line):
    user, line, _ = receipt_line
    old_sale = complete_sale(lines=[{"variant": line.variant, "quantity": 1}], channel="POS", number="BEFORE", user=user)
    correct(receipt_line)
    new_sale = complete_sale(lines=[{"variant": line.variant, "quantity": 1}], channel="POS", number="AFTER", user=user)
    old_sale.refresh_from_db()
    assert old_sale.cogs == 160 and new_sale.cogs == 80
    assert SaleAllocation.objects.get(item__sale=old_sale).unit_cost == 160


def test_audit_failure_rolls_back_both_costs(receipt_line):
    with patch("apps.inventory.receipt_corrections.StockReceiptLineCorrection.objects.create", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError):
            correct(receipt_line)
    line = receipt_line[1]
    line.refresh_from_db()
    assert line.unit_cost == line.lot.unit_cost == 160
    assert not line.corrections.exists()


@pytest.mark.parametrize("changes", [
    {"confirmed": False}, {"reason": "  "}, {"unit_cost": "NaN"}, {"unit_cost": "-1"},
    {"unit_cost": "80.001"}, {"received_quantity": "0"}, {"received_quantity": "3.0001"},
    {"variant_id": 999999}, {"unit_cost": "160"}, {"expected_updated_at": "2000-01-01T00:00:00Z"},
])
def test_invalid_corrections_leave_no_writes(receipt_line, changes):
    with pytest.raises(ValidationError):
        correct(receipt_line, **changes)
    line = receipt_line[1]
    line.refresh_from_db()
    assert line.unit_cost == line.lot.unit_cost == 160
    assert not line.corrections.exists()


def test_stale_edit_cannot_overwrite_correction(receipt_line):
    correct(receipt_line)
    with pytest.raises(ValidationError, match="changed"):
        correct(receipt_line, unit_cost="90")
    assert receipt_line[1].corrections.count() == 1


@pytest.mark.parametrize("use", ["sale", "reservation", "transfer"])
@pytest.mark.parametrize("field", ["received_quantity", "variant_id"])
def test_used_stock_requires_reversal(receipt_line, use, field):
    user, line, shelves = receipt_line
    if use == "sale":
        complete_sale(lines=[{"variant": line.variant, "quantity": 1}], channel="POS", number="SALE", user=user)
    elif use == "reservation":
        reserve_stock(variant=line.variant, quantity=1, reference="ORDER", expires_at=timezone.now(), user=user)
    else:
        transfer_stock(variant=line.variant, source=shelves[0], destination=shelves[1], quantity=1, reference="TRANSFER", user=user)
    new_variant = ProductVariant.objects.create(product=line.variant.product, name="Other", sku="OTHER", selling_price=200)
    with pytest.raises(ValidationError, match="reversal"):
        correct(receipt_line, **{field: "2" if field == "received_quantity" else new_variant.pk})
    assert not line.corrections.exists()


@pytest.mark.parametrize("quantity", ["2", "4"])
def test_unused_quantity_correction_updates_stock_and_appends_movements(receipt_line, quantity):
    _, line, _ = receipt_line
    original = list(Movement.objects.values())
    result = correct(receipt_line, received_quantity=quantity)
    assert result.received_quantity == result.lot.received_quantity == result.lot.remaining_quantity == Decimal(quantity)
    assert result.placements.get().quantity == result.lot.balances.get().quantity == Decimal(quantity)
    assert list(Movement.objects.filter(receipt_correction__isnull=True).values()) == original
    movement = result.corrections.get().movements.get()
    assert movement.quantity == 1
    assert bool(movement.source_id) == (quantity == "2")


def test_unused_variant_correction_preserves_original_movements(receipt_line):
    _, line, _ = receipt_line
    original_id = line.variant_id
    replacement = ProductVariant.objects.create(product=line.variant.product, name="Correct cable", sku="CABLE", selling_price=200)
    result = correct(receipt_line, variant_id=replacement.pk)
    assert result.variant_id == result.lot.variant_id == replacement.pk
    assert Movement.objects.get(movement_type="PURCHASE_RECEIPT").variant_id == original_id
    assert result.corrections.get().movements.count() == 2
    assert result.lot.balances.get().quantity == 3


def test_split_quantity_correction_requires_matching_placements(receipt_data):
    user, variant, shelves = receipt_data
    user.is_staff = True
    user.save()
    user.user_permissions.add(Permission.objects.get(codename="change_stockreceipt"))
    receipt = complete_stock_receipt(user=user, lines=[{
        "variant_id": variant.pk, "received_quantity": "3", "unit_cost": "160",
        "placements": [{"shelf_id": shelves[0].pk, "quantity": "2"}, {"shelf_id": shelves[1].pk, "quantity": "1"}],
    }])
    stock = user, receipt.lines.get(), shelves
    with pytest.raises(ValidationError, match="compartment"):
        correct(stock, received_quantity="4")
    result = correct(stock, received_quantity="4", placements=[{"shelf_id": shelves[0].pk, "quantity": "2"}, {"shelf_id": shelves[1].pk, "quantity": "2"}])
    assert sum(result.lot.balances.values_list("quantity", flat=True)) == 4


def test_audit_and_correction_movements_are_database_immutable(receipt_line):
    audit = correct(receipt_line, received_quantity="4").corrections.get()
    for rows in [StockReceiptLineCorrection.objects.filter(pk=audit.pk), Movement.objects.filter(receipt_correction=audit)]:
        for operation in [lambda: rows.update(**({"reason": "rewrite"} if rows.model is StockReceiptLineCorrection else {"notes": "rewrite"})), lambda: rows._raw_delete(rows.db)]:
            with pytest.raises(DatabaseError, match="immutable"):
                with transaction.atomic():
                    operation()
    audit.refresh_from_db()
    assert audit.reason == REASON


def test_api_permissions_confirmation_and_readable_audit(receipt_line):
    user, line, _ = receipt_line
    client = APIClient()
    client.force_authenticate(user)
    url = f"/api/v1/inventory/receipts/{line.receipt_id}/lines/{line.pk}/correct/"
    payload = {"variant_id": line.variant_id, "unit_cost": "80", "received_quantity": "3", "reason": REASON,
               "confirmed": True, "expected_updated_at": line.updated_at.isoformat()}
    user.user_permissions.clear()
    user = type(user).objects.get(pk=user.pk)
    client.force_authenticate(user)
    assert client.post(url, payload, format="json").status_code == 403
    with pytest.raises(PermissionDenied):
        correct((user, line, receipt_line[2]))
    user.user_permissions.add(Permission.objects.get(codename="change_stockreceipt"))
    user = type(user).objects.get(pk=user.pk)
    client.force_authenticate(user)
    assert client.post(url, {**payload, "confirmed": False}, format="json").status_code == 400
    response = client.post(url, payload, format="json")
    assert response.status_code == 200, response.data
    assert response.data["lines"][0]["corrections"][0]["reason"] == REASON
    assert client.post(url, payload, format="json").status_code == 400
    assert client.patch(url, payload, format="json").status_code == 405
    assert client.delete(url).status_code == 405
