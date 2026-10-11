"""M-Pesa prompts to the customer's phone, from each business's own till or paybill (mpesa_express.py)."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product, ProductVariant
from apps.commerce import mpesa_express
from apps.commerce.models import Payment, StkPush
from apps.core.models import Store
from apps.inventory.services import complete_stock_receipt
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, MpesaExpressSetup, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
SETUP = "/api/v1/commerce/mpesa-express/"
TILL = {"kind": "TILL", "shortcode": "5123456", "till_number": "9876543", "environment": "PRODUCTION",
        "consumer_key": "key-abcd1234", "consumer_secret": "secret-xyz", "passkey": "pass-key-123"}


@pytest.fixture
def shop(settings):
    settings.MPESA_CALLBACK_BASE_URL = "https://duka.example.com"
    owner = User.objects.create_user("duka-owner", password="Safe-pass-1848")
    cashier = User.objects.create_user("duka-cashier", password="Safe-pass-1848")
    org = Organization.objects.create(name="Duka", slug="duka", owner=owner, currency="KES")
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    Membership.objects.create(user=cashier, organization=org, role="CASHIER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
        category = Category.objects.create(name="Chargers", slug="chargers")
        charger = ProductVariant.objects.create(product=Product.objects.create(name="Charger", slug="charger", category=category),
                                                name="Standard", sku="CHG-1", selling_price=300)
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-1", received_at=timezone.now() - timedelta(hours=1),
                               lines=[{"variant_id": charger.pk, "received_quantity": "10", "unit_cost": "160"}], user=owner)
    clients = {}
    for name, user in (("owner", owner), ("cashier", cashier)):
        clients[name] = APIClient()
        clients[name].force_authenticate(user)
    return SimpleNamespace(org=org, charger=charger, **clients)


def safaricom(*answers):
    """Stands in for Safaricom: each call to the API gets the next answer."""
    return mock.patch.object(mpesa_express, "_request", side_effect=list(answers))


TOKEN = {"access_token": "tok"}


def test_a_business_without_a_till_takes_manual_payments_only(shop):
    data = shop.owner.get(SETUP).json()
    assert data["kind"] == "NONE" and data["ready"] is False and data["can_change"] is True
    assert [r["id"] for r in data["requirements"]] == ["number", "daraja", "keys", "passkey"]
    sale = shop.cashier.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": shop.charger.pk, "quantity": 1}],
                                                                 "payment_method": "MPESA", "mpesa_phone": "0712345678"}, format="json").json()
    assert "waiting_payment" in sale and "prompt" not in sale and "set up" in sale["prompt_error"]


def test_only_the_owner_sets_where_the_money_goes_and_the_keys_are_checked_with_safaricom(shop):
    assert shop.cashier.put(SETUP, TILL, format="json").status_code == 403
    assert shop.cashier.get(SETUP).json() == {"kind": "NONE", "ready": False, "simulated": False, "can_change": False}
    with safaricom({"errorMessage": "Invalid credentials"}):
        refused = shop.owner.put(SETUP, TILL, format="json").json()
    assert refused["ready"] is False and "did not accept the Consumer Key and Secret for live" in refused["status_detail"]
    with safaricom(TOKEN):
        data = shop.owner.put(SETUP, {**TILL, "consumer_key": "key-abcd9999"}, format="json").json()
    assert data["ready"] is True and data["consumer_key_hint"] == "…9999" and data["has_passkey"] is True
    assert "test prompt" in data["status_detail"]
    stored = MpesaExpressSetup.objects.get(organization=shop.org)
    assert "secret-xyz" not in stored.consumer_secret and "pass-key-123" not in stored.passkey  # encrypted at rest
    assert "secret" not in str({k: v for k, v in data.items() if k != "requirements"}).replace("has_consumer_secret", "")
    # A secret left blank keeps the saved one; changing nothing needs no new check with Safaricom.
    with safaricom() as calls:
        again = shop.owner.put(SETUP, {**TILL, "consumer_key": "", "consumer_secret": "", "passkey": ""}, format="json").json()
    assert again["ready"] is True and calls.call_count == 0
    response = shop.owner.put(SETUP, {"kind": "PAYBILL", "shortcode": "12ab"}, format="json")
    assert response.status_code == 400 and "digits only" in str(response.json())


def test_a_sale_paid_by_prompt_is_confirmed_with_the_m_pesa_code(shop):
    with safaricom(TOKEN):
        shop.owner.put(SETUP, TILL, format="json")
    sent = {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_1", "MerchantRequestID": "m1", "CustomerMessage": "Success. Request accepted"}
    with safaricom(TOKEN, sent) as calls:
        sale = shop.cashier.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": shop.charger.pk, "quantity": 2}],
                                                                     "payment_method": "MPESA", "mpesa_phone": "0712 345 678"}, format="json").json()
    body = calls.call_args_list[1].args[2]
    assert body["TransactionType"] == "CustomerBuyGoodsOnline" and body["BusinessShortCode"] == "5123456" and body["PartyB"] == "9876543"
    assert body["Amount"] == 600 and body["PhoneNumber"] == "254712345678"
    assert body["CallBackURL"].startswith("https://duka.example.com/api/v1/tenancy/mpesa/express/callback/")
    prompt = sale["prompt"]
    assert prompt["status"] == "PENDING"
    token = MpesaExpressSetup.objects.get(organization=shop.org).callback_token
    callback = {"Body": {"stkCallback": {"CheckoutRequestID": "ws_CO_1", "ResultCode": 0, "ResultDesc": "Processed",
                                         "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 600}, {"Name": "MpesaReceiptNumber", "Value": "SJK4H7XQ2P"}]}}}}
    assert APIClient().post(f"/api/v1/tenancy/mpesa/express/callback/{token}/", callback, format="json").json()["ResultCode"] == 0
    status = shop.cashier.get(f"/api/v1/commerce/prompts/{prompt['id']}/").json()
    assert status["status"] == "COMPLETED" and status["receipt_number"] == "SJK4H7XQ2P"
    with organization_context(shop.org):
        payment = Payment.objects.get(pk=sale["waiting_payment"]["id"])
        assert payment.status == "COMPLETED" and payment.provider_transaction_id == "SJK4H7XQ2P"
        assert MpesaExpressSetup.objects.get(organization=shop.org).tested_at is not None


def test_a_cancelled_prompt_leaves_the_payment_waiting_and_can_be_sent_again(shop):
    with safaricom(TOKEN):
        shop.owner.put(SETUP, {**TILL, "kind": "PAYBILL", "account_reference": "DUKA"}, format="json")
    with safaricom(TOKEN, {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_2"}) as calls:
        sale = shop.cashier.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": shop.charger.pk, "quantity": 1}],
                                                                     "payment_method": "MPESA", "mpesa_phone": "0712345678"}, format="json").json()
    body = calls.call_args_list[1].args[2]
    assert body["TransactionType"] == "CustomerPayBillOnline" and body["PartyB"] == "5123456" and body["AccountReference"] == "DUKA"
    token = MpesaExpressSetup.objects.get(organization=shop.org).callback_token
    APIClient().post(f"/api/v1/tenancy/mpesa/express/callback/{token}/",
                     {"Body": {"stkCallback": {"CheckoutRequestID": "ws_CO_2", "ResultCode": 1032, "ResultDesc": "Cancelled by user"}}}, format="json")
    status = shop.cashier.get(f"/api/v1/commerce/prompts/{sale['prompt']['id']}/").json()
    assert status["status"] == "CANCELLED" and "cancelled the prompt" in status["detail"]
    with safaricom(TOKEN, {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_3"}):
        again = shop.cashier.post(f"/api/v1/commerce/payments/{sale['waiting_payment']['id']}/prompt/", {"phone": "0712345678"}, format="json")
    assert again.status_code == 201 and again.json()["status"] == "PENDING"


def test_the_callback_needs_the_business_secret_and_a_late_one_is_asked_for(shop):
    assert APIClient().post("/api/v1/tenancy/mpesa/express/callback/wrong/", {}, format="json").status_code == 403
    with safaricom(TOKEN):
        shop.owner.put(SETUP, TILL, format="json")
    with safaricom(TOKEN, {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_4"}):
        sale = shop.cashier.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": shop.charger.pk, "quantity": 1}],
                                                                     "payment_method": "MPESA", "mpesa_phone": "0712345678"}, format="json").json()
    with organization_context(shop.org):
        StkPush.objects.filter(pk=sale["prompt"]["id"]).update(created_at=timezone.now() - timedelta(seconds=30))
    with safaricom(TOKEN, {"ResultCode": "1037", "ResultDesc": "DS timeout"}):
        status = shop.cashier.get(f"/api/v1/commerce/prompts/{sale['prompt']['id']}/").json()
    assert status["status"] == "FAILED" and "did not respond in time" in status["detail"]


def test_prompts_are_for_whole_shillings(shop, settings):
    settings.MPESA_MODE, settings.DEBUG = "simulate", True
    shop.owner.put(SETUP, TILL, format="json")
    with organization_context(shop.org):
        with pytest.raises(Exception, match="whole shillings"):
            mpesa_express.send(MpesaExpressSetup.objects.get(organization=shop.org), phone="0712345678", amount=Decimal("10.50"), user=shop.org.owner)
        push = mpesa_express.send(MpesaExpressSetup.objects.get(organization=shop.org), phone="0712345678", amount=1, user=shop.org.owner)
        StkPush.objects.filter(pk=push.pk).update(created_at=timezone.now() - timedelta(seconds=5))
        assert mpesa_express.check(StkPush.objects.get(pk=push.pk)).status == "COMPLETED"
