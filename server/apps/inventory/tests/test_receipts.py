from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.models import Movement, Shelf, ShelfStackCategory, StockBalance, StockLot, StockReceipt
from apps.inventory.services import complete_stock_receipt, create_shelf_stack
from apps.inventory.models import Zone

@pytest.fixture
def receipt_data(db):
    user=User.objects.create_user("receiver",password="test")
    zone=Zone.objects.create(store=Store.objects.create(name="LinTech"),code="RIGHT",name="Right Wall")
    category=Category.objects.create(name="Smartphone Covers",slug="smartphone-covers")
    stack=create_shelf_stack(zone=zone,user=user,display_name="Phone Covers Rack",x=0,y=0,width=100,height=100,depth=30,level_definitions=[{"compartments":2}])
    ShelfStackCategory.objects.create(stack=stack,category=category,is_primary=True)
    shelves=list(Shelf.objects.filter(level__stack=stack).order_by("id"))
    product=Product.objects.create(name="Tecno Phone Cover",slug="tecno-phone-cover",category=category)
    variant=ProductVariant.objects.create(product=product,name="Camon 22 — Dolly",sku="TEC-C22-DOL",selling_price=250)
    return user,variant,shelves

@pytest.mark.django_db
def test_receipt_creates_one_lot_and_balances_for_split(receipt_data):
    user,variant,shelves=receipt_data
    receipt=complete_stock_receipt(supplier_name="Supplier",lines=[{"variant_id":variant.id,"received_quantity":"20","unit_cost":"120","placements":[{"shelf_id":shelves[0].id,"quantity":"12"},{"shelf_id":shelves[1].id,"quantity":"8"}]}],user=user)
    assert StockReceipt.objects.get(pk=receipt.pk).lines.count()==1
    lot=StockLot.objects.get(variant=variant)
    assert lot.unit_cost==Decimal("120") and lot.balances.count()==2 and Movement.objects.filter(lot=lot,movement_type="PURCHASE_RECEIPT").count()==2

@pytest.mark.django_db
def test_receipt_rejects_mismatched_placement_atomically(receipt_data):
    user,variant,shelves=receipt_data
    with pytest.raises(ValidationError): complete_stock_receipt(lines=[{"variant_id":variant.id,"received_quantity":"5","unit_cost":"10","placements":[{"shelf_id":shelves[0].id,"quantity":"4"}]}],user=user)
    assert not StockReceipt.objects.exists() and not StockLot.objects.exists() and not StockBalance.objects.exists()

@pytest.mark.django_db
def test_receipt_idempotency_returns_same_document(receipt_data):
    user,variant,shelves=receipt_data; payload={"variant_id":variant.id,"received_quantity":"2","unit_cost":"10","placements":[{"shelf_id":shelves[0].id,"quantity":"2"}]}
    first=complete_stock_receipt(lines=[payload],user=user,idempotency_key="same-receipt"); second=complete_stock_receipt(lines=[payload],user=user,idempotency_key="same-receipt")
    assert first.pk==second.pk and StockReceipt.objects.count()==1
