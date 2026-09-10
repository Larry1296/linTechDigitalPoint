import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.models import Zone, Shelf, StockLot, StockBalance

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalogue():
    category = Category.objects.create(name="Charging Cables", slug="charging")
    brand = Brand.objects.create(name="Acme")
    zone = Zone.objects.create(store=Store.objects.create(name="Shop"), name="Zone", code="Z")
    shelf = Shelf.objects.create(zone=zone, code="PRIVATE", display_name="Private shelf",
                                 x=0, y=0, width=10, height=10)
    def create(index=0, quantity=3, reserved=0, **changes):
        product = Product.objects.create(name=f"Amaya {index}", slug=f"amaya-{index}",
                                         category=category, brand=brand, **changes)
        variant = ProductVariant.objects.create(product=product, name="White — 1m — 6A",
                                                 sku=f"SKU-{index}", selling_price="250")
        lot = StockLot.objects.create(variant=variant, reference="PRIVATE", received_quantity=quantity,
                                      remaining_quantity=quantity, unit_cost=100, received_at=timezone.now())
        StockBalance.objects.create(lot=lot, shelf=shelf, quantity=quantity, reserved=reserved)
        return variant
    return create


@pytest.mark.parametrize("query", ["", "a", " a "])
def test_short_queries(catalogue, query):
    catalogue()
    assert APIClient().get("/api/v1/store/search-suggestions/", {"q": query}).data == []


@pytest.mark.parametrize("query", ["am", "WHITE", "charging", "acme", "SKU-0", "  6a  "])
def test_matches_and_safe_shape(catalogue, query):
    variant = catalogue(reserved=1)
    rows = APIClient().get("/api/v1/store/search-suggestions/", {"q": query}).data
    assert len(rows) == 1
    assert rows[0]["id"] == variant.id
    assert rows[0]["available"] == 2
    assert rows[0]["display_name"] == "Amaya 0 — White — 1m — 6A"
    assert set(rows[0]) == {"id", "display_name", "category", "selling_price", "available", "images"}


def test_exclusions_and_limit(catalogue):
    catalogue(0, quantity=0)
    catalogue(1, reserved=3)
    catalogue(2, active=False)
    catalogue(3, ecommerce_visible=False)
    catalogue(4, product_type="SERVICE")
    inactive = catalogue(5)
    inactive.active = False
    inactive.save()
    assert APIClient().get("/api/v1/store/search-suggestions/", {"q": "am"}).data == []
    expected = [catalogue(i).id for i in range(10, 20)]
    rows = APIClient().get("/api/v1/store/search-suggestions/", {"q": "am"}).data
    assert len(rows) == 8
    assert [row["id"] for row in rows] == expected[:8]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 9])
def test_home_categories_return_all(catalogue, django_assert_num_queries, count):
    variants = [catalogue(i) for i in range(count)]
    catalogue(10, quantity=0)
    Category.objects.create(name="Empty", slug="empty")
    for index, changes in [(20, {"quantity": 0}), (21, {"product_type": "SERVICE"}),
                           (22, {"active": False}), (23, {"ecommerce_visible": False})]:
        variant = catalogue(index, **changes)
        category = Category.objects.create(name=f"Excluded {index}", slug=f"excluded-{index}")
        variant.product.category = category
        variant.product.save()
    inactive = catalogue(24)
    inactive.product.category = Category.objects.create(name="Inactive", slug="inactive", active=False)
    inactive.product.save()
    client = APIClient()
    # Categories, store, products + three prefetches, services + three
    # prefetches, and cyber services: independent of the number of categories.
    with django_assert_num_queries(11):
        response = client.get("/api/v1/store/home/")
    sections = response.data["category_sections"]
    assert len(sections) == 1
    assert sections[0]["total_available"] == count
    assert "has_more" not in sections[0]
    assert [p["id"] for p in sections[0]["products"]] == [v.id for v in variants]
    assert all(p["available"] > 0 for p in sections[0]["products"])


def test_shop_in_stock_filter_combines_category_and_search(catalogue):
    variants = [catalogue(i) for i in range(10)]
    catalogue(10, reserved=3)
    catalogue(11, quantity=0)
    catalogue(12, product_type="SERVICE")
    response = APIClient().get("/api/v1/store/products/", {
        "in_stock": "true", "search": "amaya", "product__category": variants[0].product.category_id,
    })
    assert response.status_code == 200
    assert {row["id"] for row in response.data} == {v.id for v in variants}
    assert all(row["available"] > 0 for row in response.data)

def test_home_ordering_unique_variants_and_constant_queries(catalogue, django_assert_num_queries):
    variants = [catalogue(i) for i in range(8)]
    category = Category.objects.create(name="Accessories", slug="accessories")
    for index, variant in enumerate(variants):
        variant.product.name = "Cable" if index % 2 else "Adapter"
        if index < 3:
            variant.product.category = category
        variant.product.save()
        variant.name = "White" if index % 3 else "Black"
        variant.save()
    # Include multiple variants sharing one product and identical names.
    for variant in variants[1:3]:
        variant.product = variants[0].product
        variant.name = variants[0].name
        variant.save()
    # No services here, so their prefetch queries are skipped.
    with django_assert_num_queries(8):
        sections = APIClient().get("/api/v1/store/home/").data["category_sections"]
    assert [section["name"] for section in sections] == ["Accessories", "Charging Cables"]
    ids = [row["id"] for section in sections for row in section["products"]]
    assert len(ids) == len(set(ids)) == 8
    for section in sections:
        expected = sorted(
            [v for v in variants if v.product.category_id == section["id"]],
            key=lambda v: (v.product.name, v.name, v.id),
        )
        assert [row["id"] for row in section["products"]] == [v.id for v in expected]
