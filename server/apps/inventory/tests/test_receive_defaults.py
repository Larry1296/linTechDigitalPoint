from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from apps.inventory.models import VariantPreferredLocation
from apps.inventory.services import complete_stock_receipt
from test_receipts import receipt_data  # noqa: F401  (fixture)


def defaults(user, variant):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.get(f"/api/v1/inventory/variants/{variant.pk}/receive-defaults/")


@pytest.fixture
def receiver(receipt_data):
    user, variant, shelves = receipt_data
    user.is_staff = True
    user.save()
    user.user_permissions.add(Permission.objects.get(codename="add_stockreceipt"))
    return user, variant, shelves


@pytest.mark.django_db
def test_repeats_the_last_delivery_of_the_item(receiver):
    user, variant, shelves = receiver
    complete_stock_receipt(user=user, supplier_name="Old Supplier", document_status="NO_DOCUMENT", lines=[{
        "variant_id": variant.pk, "received_quantity": "2", "unit_cost": "100",
        "placements": [{"shelf_id": shelves[0].pk, "quantity": "2"}]}])
    complete_stock_receipt(user=user, supplier_name="Luthuli Covers", document_status="NO_DOCUMENT",
                           payment={"method": "CASH", "amount": "360"}, lines=[{
        "variant_id": variant.pk, "received_quantity": "3", "unit_cost": "120",
        "placements": [{"shelf_id": shelves[1].pk, "quantity": "3"}]}])
    data = defaults(user, variant).json()
    assert data["item"]["id"] == variant.pk and Decimal(data["item"]["available"]) == 5
    assert data["supplier_name"] == "Luthuli Covers" and Decimal(data["unit_cost"]) == 120
    assert data["document_status"] == "NO_DOCUMENT" and data["payment_method"] == "CASH"
    # Its home compartment (set by its first delivery); without one, the compartment holding most of it.
    assert data["shelf"]["id"] == shelves[0].pk
    VariantPreferredLocation.objects.filter(variant=variant).delete()
    assert defaults(user, variant).json()["shelf"]["id"] == shelves[1].pk


@pytest.mark.django_db
def test_an_item_never_received_has_nothing_to_repeat(receiver):
    user, variant, _ = receiver
    data = defaults(user, variant).json()
    assert data["supplier_name"] == "" and data["unit_cost"] is None and data["shelf"] is None and data["payment_method"] == ""


@pytest.mark.django_db
def test_needs_permission_to_receive(receipt_data):
    user, variant, _ = receipt_data
    user.is_staff = True
    user.save()
    assert defaults(user, variant).status_code == 403


@pytest.mark.django_db
def test_a_new_item_follows_the_shops_last_purchase_habit(receiver):
    user, variant, shelves = receiver
    other = variant.__class__.objects.create(product=variant.product, name="Spark 40", sku="TEC-SP40", selling_price=250)
    complete_stock_receipt(user=user, supplier_name="Luthuli Covers", document_status="NO_DOCUMENT",
                           payment={"method": "MPESA", "amount": "240"}, lines=[{
        "variant_id": other.pk, "received_quantity": "2", "unit_cost": "120",
        "placements": [{"shelf_id": shelves[0].pk, "quantity": "2"}]}])
    data = defaults(user, variant).json()
    assert data["document_status"] == "NO_DOCUMENT" and data["payment_method"] == "MPESA"
    assert data["supplier_name"] == "" and data["unit_cost"] is None


@pytest.mark.django_db
def test_lists_the_suppliers_already_in_the_system(receiver):
    from apps.accounting.models import Supplier
    user, variant, shelves = receiver
    Supplier.objects.create(name="Oraimo shop")
    complete_stock_receipt(user=user, supplier_name="luthuli covers", document_status="NO_DOCUMENT", lines=[{
        "variant_id": variant.pk, "received_quantity": "1", "unit_cost": "100",
        "placements": [{"shelf_id": shelves[0].pk, "quantity": "1"}]}])
    client = APIClient()
    client.force_authenticate(user=user)
    names = client.get("/api/v1/inventory/suppliers/").json()
    assert names == sorted(set(names), key=str.casefold) and "Oraimo shop" in names
    assert [n for n in names if n.casefold() == "luthuli covers"] == ["luthuli covers"]


@pytest.mark.django_db
def test_supplier_list_needs_permission_to_receive(receipt_data):
    user, _, _ = receipt_data
    user.is_staff = True
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.get("/api/v1/inventory/suppliers/").status_code == 403


@pytest.mark.django_db
def test_names_the_top_of_the_items_category(receiver):
    from apps.catalog.models import Category
    user, variant, _ = receiver
    top = variant.product.category
    while top.parent_id:
        top = top.parent
    covers = Category.objects.create(name="Soft covers", slug="soft-covers", parent=top)
    variant.product.category = Category.objects.create(name="Tecno", slug="tecno-soft", parent=covers)
    variant.product.save()
    assert defaults(user, variant).json()["root_category_id"] == top.pk
