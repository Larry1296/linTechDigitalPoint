import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from apps.catalog.models import Brand, Category, Product, ProductVariant, PriceHistory


@pytest.fixture
def catalog(db):
    user = User.objects.create_superuser("pos-owner", "owner@example.com", "test")
    client = APIClient()
    client.force_authenticate(user)
    category = Category.objects.create(name="Accessories", slug="accessories")
    brand = Brand.objects.create(name="Acme")
    product = Product.objects.create(name="Cable", slug="cable", category=category, brand=brand, ecommerce_visible=False)
    variant = ProductVariant.objects.create(product=product, name="Crimson", sku="CODE-123", barcode="987654", selling_price=100)
    return client, product, variant


@pytest.mark.parametrize("query", ["caBLE", "crimSON", "accessORIES", "acME", "code-1", "8765"])
def test_internal_search_fields(catalog, query):
    client, product, variant = catalog
    for url in ("/api/v1/commerce/pos/catalog/", "/api/v1/catalog/products/search-suggestions/"):
        rows = client.get(url, {"q": query}).json()
        assert [row["id"] for row in rows] == [variant.id]
        assert rows[0]["category_id"] == product.category_id
        assert rows[0]["category_name"] == "Accessories"


def test_order_exact_priority_and_batched_stock(catalog):
    client, product, variant = catalog
    for i in range(55):
        ProductVariant.objects.create(product=product, name=f"AAA{i:02}", sku=f"OTHER{i}")
    with CaptureQueriesContext(connection) as queries:
        rows = client.get("/api/v1/commerce/pos/catalog/").json()
    assert len(rows) == 56
    assert rows[-1]["id"] == variant.id
    assert len([q for q in queries if '"inventory_stockbalance"' in q["sql"]]) == 1
    product.name = "CODE-123 cable"
    product.save()
    assert client.get("/api/v1/commerce/pos/catalog/", {"q": "CODE-123"}).json()[0]["id"] == variant.id
    assert client.get("/api/v1/catalog/products/search-suggestions/", {"q": " c "}).json() == []


def test_edit_permissions_price_history_and_no_inventory_write(catalog):
    client, product, variant = catalog
    response = client.patch(f"/api/v1/catalog/variants/{variant.id}/", {"selling_price": "150", "name": "Blue", "physical": 999}, format="json")
    assert response.status_code == 200
    assert response.json()["physical"] == 0
    assert PriceHistory.objects.get(variant=variant).price == 150
    assert client.patch(f"/api/v1/catalog/products/{product.id}/", {"name": "Cable updated"}, format="json").status_code == 200
    assert client.get("/api/v1/commerce/pos/catalog/").json()[0]["available"] == 0
    client.force_authenticate(User.objects.create_user("cashier", is_staff=True))
    assert client.patch(f"/api/v1/catalog/variants/{variant.id}/", {"selling_price": 10}).status_code == 403
    assert client.patch(f"/api/v1/catalog/products/{product.id}/", {"name": "Denied"}).status_code == 403
    client.force_authenticate(None)
    assert client.get("/api/v1/commerce/pos/catalog/").status_code == 403
    assert client.get("/api/v1/catalog/products/search-suggestions/", {"q": "Cable"}).status_code == 403
