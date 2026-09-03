import os
from decimal import Decimal
import pytest
from django.contrib.auth.models import Group,User
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import CustomerProfile
from apps.catalog.models import Category,Product,ProductVariant
from apps.commerce.models import Cart,CartItem,Order,OrderItem,Payment,Sale
from apps.commerce.services import complete_reserved_order
from apps.core.models import Store
from apps.core.setup import ensure_initial_setup
from apps.inventory.models import Reservation,Shelf,StockBalance,Zone
from apps.inventory.services import receive_stock
@pytest.mark.django_db
def test_create_owner_repairs_existing_user(monkeypatch):
    user=User.objects.create_user("larry",password="preserve-me"); monkeypatch.setenv("OWNER_USERNAME","larry")
    call_command("create_owner","--noinput","--username","larry","--email","owner@lintech.test","--first-name","Larry")
    user.refresh_from_db();assert user.is_staff and user.is_superuser and user.is_active;assert user.groups.filter(name="Owner").exists();assert user.check_password("preserve-me");assert Store.objects.filter(name="LinTech Digital Point").exists();assert Zone.objects.count()==5
@pytest.mark.django_db
def test_create_owner_fresh_database(monkeypatch):
    monkeypatch.setenv("OWNER_PASSWORD","A-strong-owner-password-1296")
    call_command("create_owner","--noinput","--username","first-owner","--email","owner@lintech.test","--first-name","Larry")
    user=User.objects.get(username="first-owner");assert user.is_active and user.is_staff and user.is_superuser;assert user.groups.get().name=="Owner"
@pytest.mark.django_db
def test_role_permissions_are_real():
    _,groups=ensure_initial_setup();assert groups["Cashier"].permissions.filter(codename="add_sale").exists();assert groups["Stock Controller"].permissions.filter(content_type__app_label="inventory").exists();assert groups["Manager"].permissions.filter(content_type__app_label="commerce").exists();assert not groups["Ecommerce Customer"].permissions.exists()
@pytest.mark.django_db
def test_customer_cannot_access_internal_locations():
    ensure_initial_setup();user=User.objects.create_user("customer",password="Strong-pass-1296");CustomerProfile.objects.create(user=user);user.groups.add(Group.objects.get(name="Ecommerce Customer"));client=APIClient();client.force_authenticate(user)
    assert client.get("/api/v1/locations/zones/").status_code==403
@pytest.fixture
def reserved_order(db):
    ensure_initial_setup();customer=User.objects.create_user("buyer",password="Strong-pass-1296");owner=User.objects.create_superuser("owner","o@x.test","Strong-pass-1296");store=Store.objects.first();zone=Zone.objects.get(store=store,code="LEFT");shelf=Shelf.objects.create(zone=zone,code="L-SH-0999",display_name="Covers",x=1,y=2,width=33,height=17,created_by=owner);cat=Category.objects.create(name="Cases",slug="cases");product=Product.objects.create(name="A05 Cover",slug="a05-cover",category=cat);variant=ProductVariant.objects.create(product=product,name="Black",sku="A05-X",selling_price=250);lot=receive_stock(variant=variant,placements=[{"shelf":shelf,"quantity":1}],unit_cost=120,reference="PO-X",user=owner)
    from apps.inventory.services import reserve_stock
    reservation=reserve_stock(variant=variant,quantity=1,reference="LT-WEB-X",expires_at=timezone.now()+timezone.timedelta(minutes=30),user=customer);order=Order.objects.create(number="LT-WEB-X",customer=customer,subtotal=250,total=250);OrderItem.objects.create(order=order,variant=variant,product_name=product.name,variant_name=variant.name,sku=variant.sku,quantity=1,unit_price=250,reservation=reservation);return order,reservation,lot,shelf,owner
@pytest.mark.django_db
def test_reserved_order_consumes_exact_allocation_once(reserved_order):
    order,reservation,lot,shelf,owner=reserved_order;sale=complete_reserved_order(order=order,payment_method="MPESA",provider_transaction_id="MPESA-1",idempotency_key="callback-1",user=owner);again=complete_reserved_order(order=order,payment_method="MPESA",provider_transaction_id="MPESA-1",idempotency_key="callback-1",user=owner)
    balance=StockBalance.objects.get(lot=lot,shelf=shelf);reservation.refresh_from_db();assert sale.pk==again.pk;assert balance.quantity==0 and balance.reserved==0;assert reservation.status==Reservation.CONSUMED and not reservation.active;assert Sale.objects.filter(order=order).count()==1;assert Payment.objects.filter(sale=sale,status="COMPLETED").count()==1;assert sale.cogs==120
@pytest.mark.django_db
def test_customer_order_ownership():
    a=User.objects.create_user("a");b=User.objects.create_user("b");order=Order.objects.create(number="PRIVATE",customer=b,subtotal=10,total=10);client=APIClient();client.force_authenticate(a);assert client.get(f"/api/v1/commerce/orders/{order.id}/").status_code==404

@pytest.mark.django_db
def test_anonymous_cart_survives_registration_and_checkout(reserved_order):
    order,old_reservation,lot,shelf,owner=reserved_order
    OrderItem.objects.filter(order=order).delete();old_reservation.delete();order.delete()
    balance=StockBalance.objects.get(lot=lot,shelf=shelf);balance.reserved=0;balance.save()
    variant=lot.variant;client=APIClient()
    assert client.post("/api/v1/commerce/cart/",{"variant_id":variant.id,"quantity":1},format="json").status_code==200
    registered=client.post("/api/v1/auth/register/",{"username":"newbuyer","email":"new@buyer.test","first_name":"New Buyer","password":"Strong-pass-1296","confirm_password":"Strong-pass-1296"},format="json")
    assert registered.status_code==201
    cart=client.get("/api/v1/commerce/cart/").json();assert len(cart["items"])==1
    checkout=client.post("/api/v1/commerce/checkout/",{"fulfillment_method":"PICKUP","payment_method":"CASH_ON_PICKUP"},format="json")
    assert checkout.status_code==201;assert checkout.json()["items"][0]["unit_price"]=="250.00";assert StockBalance.objects.get().reserved==1

@pytest.mark.django_db
def test_shared_login_accepts_customer_staff_and_email():
    ensure_initial_setup();customer=User.objects.create_user("customer-login","buyer@lintech.test","Strong-pass-1296");CustomerProfile.objects.create(user=customer);staff=User.objects.create_user("staff-login","staff@lintech.test","Strong-pass-1296",is_staff=True)
    customer_response=APIClient().post("/api/v1/auth/login/",{"credential":"buyer@lintech.test","password":"Strong-pass-1296"},format="json");staff_response=APIClient().post("/api/v1/auth/login/",{"credential":"staff-login","password":"Strong-pass-1296"},format="json")
    assert customer_response.status_code==200 and not customer_response.json()["is_staff"];assert staff_response.status_code==200 and staff_response.json()["is_staff"]

@pytest.mark.django_db
def test_anonymous_cart_survives_customer_login(reserved_order):
    _,reservation,lot,_,_=reserved_order;OrderItem.objects.filter(reservation=reservation).delete();reservation.delete();balance=StockBalance.objects.get(lot=lot);balance.reserved=0;balance.save();customer=User.objects.create_user("returning","returning@lintech.test","Strong-pass-1296");client=APIClient();client.post("/api/v1/commerce/cart/",{"variant_id":lot.variant_id,"quantity":2},format="json")
    response=client.post("/api/v1/auth/login/",{"credential":"returning","password":"Strong-pass-1296"},format="json");cart=client.get("/api/v1/commerce/cart/").json()
    assert response.status_code==200;assert len(cart["items"])==1 and cart["items"][0]["quantity"]=="2.000"

@pytest.mark.django_db
def test_anonymous_and_customer_carts_merge_one_line(reserved_order):
    _,reservation,lot,_,_=reserved_order;OrderItem.objects.filter(reservation=reservation).delete();reservation.delete();balance=StockBalance.objects.get(lot=lot);balance.reserved=0;balance.quantity=5;balance.save();customer=User.objects.create_user("merge-user",password="Strong-pass-1296");owned=Cart.objects.create(customer=customer);CartItem.objects.create(cart=owned,variant=lot.variant,quantity=2);client=APIClient();client.post("/api/v1/commerce/cart/",{"variant_id":lot.variant_id,"quantity":1},format="json")
    client.post("/api/v1/auth/login/",{"credential":"merge-user","password":"Strong-pass-1296"},format="json");cart=client.get("/api/v1/commerce/cart/").json()
    assert len(cart["items"])==1 and cart["items"][0]["quantity"]=="3.000"

@pytest.mark.django_db
def test_failed_authentication_never_discards_cart(reserved_order):
    _,reservation,lot,_,_=reserved_order;OrderItem.objects.filter(reservation=reservation).delete();reservation.delete();balance=StockBalance.objects.get(lot=lot);balance.reserved=0;balance.save();client=APIClient();client.post("/api/v1/commerce/cart/",{"variant_id":lot.variant_id,"quantity":1},format="json")
    assert client.post("/api/v1/auth/login/",{"credential":"missing","password":"wrong"},format="json").status_code==400
    assert client.post("/api/v1/auth/register/",{"username":"x","email":"bad","password":"short","confirm_password":"different"},format="json").status_code==400
    cart=client.get("/api/v1/commerce/cart/").json();assert len(cart["items"])==1 and cart["items"][0]["quantity"]=="1.000"
