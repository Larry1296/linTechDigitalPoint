import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product
from apps.inventory.models import Zone, StockReceipt


@pytest.fixture
def owner(db):
    client = APIClient()
    user = User.objects.create(username="owner", is_staff=True, is_superuser=True)
    client.force_authenticate(user)
    return client


def test_owner_manually_creates_first_root_category(owner):
    assert not Category.objects.exists()
    response = owner.post("/api/v1/catalog/categories/", {"name": "Mobile Accessories", "parent": None}, format="json")
    assert response.status_code == 201
    category = Category.objects.get()
    assert category.slug == "mobile-accessories" and category.parent is None
    assert not Product.objects.exists() and not Zone.objects.exists() and not StockReceipt.objects.exists()
    assert owner.post("/api/v1/catalog/categories/", {"name": " mobile accessories "}, format="json").status_code == 400


def test_editing_category_preserves_slug_and_rejects_cycles(owner):
    root = Category.objects.create(name="Mobile Accessories", slug="mobile-accessories")
    child = Category.objects.create(name="Cables", slug="cables", parent=root)
    response = owner.patch(f"/api/v1/catalog/categories/{root.pk}/", {"parent": child.pk}, format="json")
    assert response.status_code == 400
    response = owner.patch(f"/api/v1/catalog/categories/{child.pk}/", {"name": "USB cables", "active": False}, format="json")
    assert response.status_code == 200
    child.refresh_from_db()
    assert child.name == "USB cables" and child.slug == "cables" and not child.active
    other = Category.objects.create(name="Other", slug="other", parent=root)
    assert owner.patch(f"/api/v1/catalog/categories/{other.pk}/", {"name": "USB cables"}, format="json").status_code == 400


def test_category_creation_requires_staff_permission(db):
    client = APIClient()
    assert client.post("/api/v1/catalog/categories/", {"name": "Mobile Accessories"}).status_code == 403
    client.force_authenticate(User.objects.create(username="staff", is_staff=True))
    assert client.post("/api/v1/catalog/categories/", {"name": "Mobile Accessories"}).status_code == 403
    assert not Category.objects.exists()
