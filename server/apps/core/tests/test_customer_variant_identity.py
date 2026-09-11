from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product, ProductVariant, ProductOptionType, ProductOptionValue, ProductVariantOptionValue
from apps.core.models import Store
from apps.inventory.models import Zone, ShelfStackCategory, StockReceipt, StockLot, Movement
from apps.inventory.services import create_shelf_stack, complete_stock_receipt
from apps.commerce.models import Order, CartItem


@pytest.fixture
def cables(db):
    category = Category.objects.create(name="Charging Cables", slug="charging-cables")
    product = Product.objects.create(name="Amaya USB Charging Cable", slug="amaya-usb", category=category)
    product.images.create(image_url="https://example.test/cable.jpg")
    store = Store.objects.create(name="Test shop")
    zone = Zone.objects.create(store=store, code="A", name="Zone A")
    rack = create_shelf_stack(zone=zone, user=None, display_name="Accessories", x=0, y=0, width=2, height=2, depth=1, level_definitions=[{"compartments": 2}])
    ShelfStackCategory.objects.create(stack=rack, category=category)
    shelves = list(zone.shelves.order_by("pk"))
    variants = []
    connector = ProductOptionType.objects.create(product=product, name="Connector type")
    for index, name in enumerate(("Type-B (Micro-USB)", "Type-C")):
        variant = ProductVariant.objects.create(product=product, name=f"AM-M01 — {name} — White — 1.2m — 3.1A", sku=f"CABLE-{index}", selling_price=250 + index * 50)
        value = ProductOptionValue.objects.create(option_type=connector, value=name)
        ProductVariantOptionValue.objects.create(variant=variant, value=value)
        complete_stock_receipt(external_reference=f"TEST-{index}", lines=[{"variant_id": variant.pk, "received_quantity": 5, "unit_cost": 100, "placements": [{"shelf_id": shelves[index].pk, "quantity": 5}]}])
        variants.append(variant)
    return variants


def test_public_variants_and_search_have_exact_identity(cables):
    client = APIClient()
    rows = client.get("/api/v1/store/products/").data
    assert len(rows) == 2
    variants_by_id = {variant.pk: variant for variant in cables}
    for row in rows:
        variant = variants_by_id[row["variant_id"]]
        assert row["display_name"] == f"Amaya USB Charging Cable — {variant.name}"
        assert row["variant_id"] == variant.pk and row["product_id"] == variant.product_id
        assert row["variant_name"] == variant.name and row["sku"] == variant.sku
        assert Decimal(row["available"]) == 5 and row["images"]
        assert row["variant_count"] == 2 and row["attributes"][0]["name"] == "Connector type"
        assert not set(row) & {"unit_cost", "lots", "locations", "shelf", "barcode"}
    detail = client.get(f"/api/v1/store/products/{cables[0].pk}/").data
    assert {v["variant_id"] for v in detail["variants"]} == {v.pk for v in cables}
    rows = client.get("/api/v1/store/products/?search=Type-C").data
    assert len(rows) == 1 and rows[0]["variant_id"] == cables[1].pk


def test_variant_identity_survives_cart_checkout_and_catalog_rename(cables):
    client = APIClient()
    client.force_authenticate(User.objects.create(username="buyer"))
    for variant in cables:
        response = client.post("/api/v1/commerce/cart/", {"variant_id": variant.pk, "quantity": 1, "unit_price": "0.01"}, format="json")
        assert response.status_code == 200
    cart = response.data
    names = {f"Amaya USB Charging Cable — {v.name}" for v in cables}
    assert {item["display_name"] for item in cart["items"]} == names
    assert {item["variant_id"] for item in cart["items"]} == {v.pk for v in cables}
    response = client.post("/api/v1/commerce/checkout/", {"fulfillment_method": "PICKUP", "payment_method": "CASH_ON_PICKUP", "total": "0.01"}, format="json")
    assert response.status_code == 201 and Decimal(response.data["total"]) == 550
    assert {item["display_name"] for item in response.data["items"]} == names
    order = Order.objects.get()
    ProductVariant.objects.filter(pk__in=[v.pk for v in cables]).update(name="Renamed afterwards")
    Product.objects.filter(pk=cables[0].product_id).update(name="New catalog name")
    history = client.get(f"/api/v1/commerce/orders/{order.pk}/").data
    assert {item["display_name"] for item in history["items"]} == names
    assert {item["variant_id"] for item in history["items"]} == {v.pk for v in cables}
    assert all(item["pick_locations"] is None for item in history["items"])
    assert {item["display_name"] for item in client.get("/api/v1/commerce/orders/").data[0]["items"]} == names
    assert StockReceipt.objects.count() == StockLot.objects.count() == 2
    assert Movement.objects.filter(movement_type="PURCHASE_RECEIPT").count() == 2


@pytest.mark.parametrize("quantity", [6, 0, -1, "NaN", "invalid"])
def test_cart_rejects_invalid_or_unavailable_quantity(cables, quantity):
    response = APIClient().post("/api/v1/commerce/cart/", {"variant_id": cables[0].pk, "quantity": quantity}, format="json")
    assert response.status_code == 400
    assert not CartItem.objects.exists()


@pytest.mark.parametrize("change", ["inactive", "hidden", "zero_price", "stock"])
def test_checkout_revalidates_variant(cables, change):
    client = APIClient()
    client.force_authenticate(User.objects.create(username="buyer"))
    variant = cables[0]
    assert client.post("/api/v1/commerce/cart/", {"variant_id": variant.pk, "quantity": 2}, format="json").status_code == 200
    if change == "inactive":
        ProductVariant.objects.filter(pk=variant.pk).update(active=False)
    elif change == "hidden":
        Product.objects.filter(pk=variant.product_id).update(ecommerce_visible=False)
    elif change == "zero_price":
        ProductVariant.objects.filter(pk=variant.pk).update(selling_price=0)
    else:
        from django.db import transaction
        from apps.inventory.services import consume_stock_fifo
        with transaction.atomic():
            consume_stock_fifo(variant=variant, quantity=4, reference="TEST-SALE", movement_type="SALE")
    response = client.post("/api/v1/commerce/checkout/", {"fulfillment_method": "PICKUP"}, format="json")
    assert response.status_code == 400
    assert not Order.objects.exists()
    assert CartItem.objects.get().quantity == 2
