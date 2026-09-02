import pytest
from django.contrib.auth.models import User
from catalog.models import Category,PriceHistory,Product,ProductVariant
@pytest.mark.django_db
def test_product_and_price_history():
    user=User.objects.create_user("manager"); cat=Category.objects.create(name="Accessories",slug="accessories"); product=Product.objects.create(name="Cable",slug="cable",category=cat); variant=ProductVariant.objects.create(product=product,sku="CAB-1",selling_price=250); PriceHistory.objects.create(variant=variant,price=250,changed_by=user); variant.selling_price=300; variant.save(); PriceHistory.objects.create(variant=variant,price=300,changed_by=user); assert list(variant.price_history.values_list("price",flat=True))==[250,300]

