import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category,PriceHistory,Product,ProductVariant
from apps.inventory.models import StockBalance,VariantPreferredLocation
@pytest.mark.django_db
def test_product_and_price_history():
    user=User.objects.create_user("manager"); cat=Category.objects.create(name="Accessories",slug="accessories"); product=Product.objects.create(name="Cable",slug="cable",category=cat); variant=ProductVariant.objects.create(product=product,sku="CAB-1",selling_price=250); PriceHistory.objects.create(variant=variant,price=250,changed_by=user); variant.selling_price=300; variant.save(); PriceHistory.objects.create(variant=variant,price=300,changed_by=user); assert list(variant.price_history.values_list("price",flat=True))==[250,300]

@pytest.mark.django_db
def test_software_service_creation_has_cost_but_no_physical_stock():
    owner=User.objects.create_superuser("service-owner","owner@example.test","Strong-pass-1296");category=Category.objects.create(name="Software Services",slug="software-services");client=APIClient();client.force_authenticate(owner)
    response=client.post("/api/v1/catalog/products/create-with-stock/",{"name":"Windows Installation","category_id":category.id,"product_type":"SERVICE","variant_name":"Windows 11","sku":"SVC-WIN11","selling_price":"1500","service_cost":"200","opening_quantity":"10"},format="json")
    assert response.status_code==201
    variant=ProductVariant.objects.get(pk=response.json()["variant_id"])
    assert variant.service_cost==200 and variant.product.product_type==Product.SERVICE
    assert not StockBalance.objects.filter(lot__variant=variant).exists()
    assert not VariantPreferredLocation.objects.filter(variant=variant).exists()
