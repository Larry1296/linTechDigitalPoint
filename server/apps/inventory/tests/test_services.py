from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.catalog.models import Category,Product,ProductVariant
from apps.commerce.models import SaleAllocation
from apps.core.models import Store
from apps.inventory.models import Shelf,StockBalance,Zone
from apps.inventory.services import complete_sale,create_shelf,receive_stock,reserve_stock,release_reservation,transfer_stock,update_shelf
@pytest.fixture
def data(db):
    user=User.objects.create_user("owner",password="test"); store=Store.objects.create(name="LinTech Digital Point"); zone=Zone.objects.create(store=store,code="LEFT",name="Left Wall",width=Decimal("300"),height=Decimal("220"))
    a=Shelf.objects.create(zone=zone,code="L-SH-0001",display_name="Samsung Phone Covers",x=5,y=10,width=80,height=35,created_by=user); b=Shelf.objects.create(zone=zone,code="L-SH-0002",display_name="Chargers & Cables",x=100,y=15,width=115,height=55,created_by=user)
    cat=Category.objects.create(name="Phone Covers",slug="phone-covers"); product=Product.objects.create(name="Samsung Galaxy A05 Cover",slug="samsung-a05-cover",category=cat); variant=ProductVariant.objects.create(product=product,name="Black",sku="A05-BLK",selling_price=250)
    return user,a,b,variant
@pytest.mark.django_db
def test_dynamic_shelves_and_multiple_locations(data):
    user,a,b,v=data; assert a.width!=b.width and a.height!=b.height
    lot=receive_stock(variant=v,placements=[{"shelf":a,"quantity":6},{"shelf":b,"quantity":4}],unit_cost=120,reference="PO-1",user=user)
    assert lot.unit_cost==120 and sum(x.quantity for x in StockBalance.objects.all())==10
@pytest.mark.django_db
def test_batches_fifo_sale_and_profit(data):
    user,a,b,v=data
    first=receive_stock(variant=v,placements=[{"shelf":a,"quantity":6},{"shelf":b,"quantity":4}],unit_cost=120,reference="PO-1",user=user)
    second=receive_stock(variant=v,placements=[{"shelf":b,"quantity":5}],unit_cost=140,reference="PO-2",user=user)
    sale=complete_sale(lines=[{"variant":v,"quantity":7}],channel="POS",number="LT-0001",user=user)
    assert sale.cogs==Decimal("840.00000"); assert sale.gross_profit==Decimal("910.00000")
    assert SaleAllocation.objects.filter(item__sale=sale,lot=first).count()>0
    assert first.received_quantity==10 and second.unit_cost==140
    assert sum(x.quantity for x in StockBalance.objects.all())==8
@pytest.mark.django_db
def test_transfer_conserves_total(data):
    user,a,b,v=data; receive_stock(variant=v,placements=[{"shelf":a,"quantity":10}],unit_cost=120,reference="PO",user=user)
    transfer_stock(variant=v,source=a,destination=b,quantity=4,reference="TX",user=user)
    assert sum(x.quantity for x in StockBalance.objects.all())==10; assert StockBalance.objects.get(shelf=b).quantity==4
@pytest.mark.django_db
def test_reservation_release_and_oversell(data):
    user,a,b,v=data; receive_stock(variant=v,placements=[{"shelf":a,"quantity":5}],unit_cost=120,reference="PO",user=user)
    reservation=reserve_stock(variant=v,quantity=3,reference="WEB-1",expires_at=timezone.now()+timezone.timedelta(minutes=30),user=user)
    assert StockBalance.objects.get().reserved==3
    with pytest.raises(ValidationError): reserve_stock(variant=v,quantity=3,reference="WEB-2",expires_at=timezone.now())
    release_reservation(reservation,user); assert StockBalance.objects.get().reserved==0
@pytest.mark.django_db
def test_service_sale_has_no_inventory(data):
    user,a,b,v=data; v.product.product_type="SERVICE"; v.product.save(); v.service_cost=Decimal("10"); v.save()
    sale=complete_sale(lines=[{"variant":v,"quantity":2}],channel="POS",number="LT-SVC",user=user)
    assert sale.cogs==20 and not StockBalance.objects.exists()

@pytest.mark.django_db
def test_shelf_code_is_collision_safe_and_history_preserves_identity(data):
    user,a,b,v=data;zone=a.zone;zone.next_shelf_number=1;zone.save()
    shelf=create_shelf(zone=zone,user=user,display_name="New shelf",x=4,y=8,width=47,height=19)
    assert shelf.code=="L-SH-0003"
    original=shelf.code;update_shelf(shelf=shelf,user=user,display_name="Repurposed shelf")
    shelf.refresh_from_db();assert shelf.code==original;assert list(shelf.history.values_list("event",flat=True))==["CREATED","RENAMED"]
