import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from catalog.models import Category,Product,ProductVariant
@pytest.mark.django_db
def test_public_catalog_never_leaks_cost_or_shelves():
    c=Category.objects.create(name="Cables",slug="cables"); p=Product.objects.create(name="Type C",slug="type-c",category=c); ProductVariant.objects.create(product=p,sku="TC1",selling_price=250)
    response=APIClient().get("/api/v1/store/products/"); assert response.status_code==200
    text=response.content.decode(); assert "selling_price" in text; assert "unit_cost" not in text and "shelf" not in text and "cogs" not in text
@pytest.mark.django_db
def test_locations_require_login():
    assert APIClient().get("/api/v1/locations/zones/").status_code in (401,403)

