"""The till's checkout: the basket is charged, the customer pays by cash, the till, a prompt, bank or a mix, and only then
is the sale made (checkout.py). Till payments are never matched by their amount alone."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product, ProductVariant
from apps.commerce import mpesa_express
from apps.commerce.models import Checkout, IncomingMpesaPayment, Payment, Sale, StkPush
from apps.core.models import Store
from apps.inventory.models import StockBalance
from apps.inventory.services import complete_stock_receipt
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, MpesaExpressSetup, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal
CHECKOUTS = "/api/v1/commerce/pos/checkouts/"


@pytest.fixture
def shop(settings):
    settings.MPESA_CALLBACK_BASE_URL = "https://duka.example.com"
    owner = User.objects.create_user("duka-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Duka", slug="duka", owner=owner, currency="KES")
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    clients = {"owner": APIClient()}
    clients["owner"].force_authenticate(owner)
    for name in ("amina", "brian"):
        user = User.objects.create_user(name, password="Safe-pass-1848")
        Membership.objects.create(user=user, organization=org, role="CASHIER")
        clients[name] = APIClient()
        clients[name].force_authenticate(user)
    with organization_context(org):
        Store.objects.create(name="Main")
        category = Category.objects.create(name="Chargers", slug="chargers")
        charger = ProductVariant.objects.create(product=Product.objects.create(name="Charger", slug="charger", category=category),
                                                name="Standard", sku="CHG-1", selling_price=300)
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-1", received_at=timezone.now() - timedelta(hours=1),
                               lines=[{"variant_id": charger.pk, "received_quantity": "10", "unit_cost": "160"}], user=owner)
    till = MpesaExpressSetup.objects.create(organization=org, kind=MpesaExpressSetup.TILL, shortcode="5123456", till_number="9876543",
                                            callback_token=uuid4().hex, till_token=uuid4().hex, verified_at=timezone.now(),
                                            till_registered_at=timezone.now())
    return SimpleNamespace(org=org, charger=charger, till=till, **clients)


def charge(client, shop, quantity=1, **extra):
    response = client.post(CHECKOUTS, {"items": [{"variant_id": shop.charger.pk, "quantity": quantity}], "idempotency_key": uuid4().hex, **extra},
                           format="json")
    assert response.status_code == 201, response.content
    return response.json()


def pay(client, checkout, **values):
    return client.post(f"{CHECKOUTS}{checkout['id']}/pay/", values, format="json")


def notice(shop, code, amount, when=None, **extra):
    when = when or timezone.localtime().strftime("%Y%m%d%H%M%S")
    return APIClient().post(f"/api/v1/tenancy/payments/till/{shop.till.till_token}/confirm/",
                            {"TransactionType": "Buy Goods", "TransID": code, "TransTime": when, "TransAmount": str(amount),
                             "BusinessShortCode": "5123456", "BillRefNumber": "", "MSISDN": "25470****149", "FirstName": "Wanjiru", **extra},
                            format="json")


def in_stock(shop):
    with organization_context(shop.org):
        return StockBalance.objects.filter(lot__variant=shop.charger).aggregate(total=Sum("quantity"))["total"]


def test_the_basket_is_charged_without_selling_and_cash_completes_it_with_change(shop):
    checkout = charge(shop.amina, shop, quantity=2)
    assert checkout["status"] == "AWAITING" and D(checkout["total"]) == 600 and D(checkout["left"]) == 600
    with organization_context(shop.org):
        assert not Sale.objects.exists()
    assert in_stock(shop) == 10  # nothing left the shelf
    done = pay(shop.amina, checkout, method="CASH", cash_given="1000").json()
    assert done["status"] == "COMPLETED" and done["receipt"]["receipt_number"] == checkout["number"]
    assert D(done["payments"][0]["change"]) == 400
    assert in_stock(shop) == 8
    with organization_context(shop.org):
        payment = Payment.objects.get()
        assert (payment.method, payment.amount, payment.status) == ("CASH", D("600.00"), "COMPLETED")
    # The same request again charges nothing new.
    again = shop.amina.post(f"{CHECKOUTS}{checkout['id']}/pay/", {"method": "CASH", "cash_given": "600"}, format="json")
    assert again.status_code == 400 and "not waiting for payment" in str(again.json())


def test_two_customers_paying_the_same_amount_at_the_same_moment_are_never_matched_by_amount(shop):
    first, second = charge(shop.amina, shop), charge(shop.brian, shop)
    assert notice(shop, "SKA1111111", 300).status_code == 200
    assert notice(shop, "SKB2222222", 300).status_code == 200  # same amount, same second
    # Neither checkout was paid by itself: an equal amount proves nothing.
    seen = shop.amina.get(f"{CHECKOUTS}{first['id']}/").json()
    assert seen["status"] == "AWAITING" and {row["code"] for row in seen["till_payments"]} == {"SKA1111111", "SKB2222222"}
    row = next(row for row in seen["till_payments"] if row["code"] == "SKB2222222")
    assert row["payer_phone"] == "25470****149" and row["payer_name"] == "Wanjiru"
    # Each cashier attaches their own customer's payment (Amina by tapping it, Brian with the code from the SMS).
    assert pay(shop.amina, first, method="TILL", incoming_id=row["id"]).json()["status"] == "COMPLETED"
    taken = pay(shop.brian, second, method="TILL", code="skb2222222")
    assert taken.status_code == 400 and "already used for another sale" in str(taken.json())
    assert pay(shop.brian, second, method="TILL", code="SKA 1111111").json()["status"] == "COMPLETED"
    with organization_context(shop.org):
        assert sorted(Payment.objects.values_list("provider_transaction_id", flat=True)) == ["SKA1111111", "SKB2222222"]
        assert set(IncomingMpesaPayment.objects.values_list("status", flat=True)) == {"USED"}


def test_a_repeated_notice_is_one_payment_and_a_forged_one_is_refused(shop, settings):
    assert notice(shop, "SKC3333333", 300).status_code == 200
    assert notice(shop, "SKC3333333", 300).status_code == 200
    forged = APIClient().post("/api/v1/tenancy/payments/till/not-the-secret/confirm/", {"TransID": "FAKE000001", "TransAmount": "300"}, format="json")
    assert forged.status_code == 403
    settings.MPESA_CALLBACK_IPS = ["196.201.214.200"]
    assert notice(shop, "SKD4444444", 300).status_code == 403  # not from Safaricom's addresses
    with organization_context(shop.org):
        assert list(IncomingMpesaPayment.objects.values_list("transaction_id", flat=True)) == ["SKC3333333"]


def test_a_code_safaricom_never_reported_is_not_proof_of_payment(shop):
    checkout = charge(shop.amina, shop)
    refused = pay(shop.amina, checkout, method="TILL", code="QWERTY1234")
    assert refused.status_code == 400 and "has not reported a payment with the code QWERTY1234" in str(refused.json())
    # A business not connected to Safaricom takes the code as typed, marked as not checked.
    MpesaExpressSetup.objects.filter(pk=shop.till.pk).update(till_registered_at=None)
    done = pay(shop.amina, checkout, method="TILL", code="QWERTY1234").json()
    assert done["status"] == "COMPLETED" and done["payments"][0]["checked_with_safaricom"] is False
    assert "not checked with Safaricom" in done["payments"][0]["detail"]


def test_underpaid_by_till_then_the_rest_in_cash_and_overpaid_leaves_the_extra_traceable(shop):
    checkout = charge(shop.amina, shop)
    notice(shop, "SKE5555555", 200)
    part = pay(shop.amina, checkout, method="TILL", code="SKE5555555").json()
    assert part["status"] == "PART_PAID" and D(part["left"]) == 100
    assert pay(shop.amina, checkout, method="CASH", cash_given="100").json()["status"] == "COMPLETED"
    over = charge(shop.amina, shop)
    notice(shop, "SKF6666666", 350)
    done = pay(shop.amina, over, method="TILL", code="SKF6666666").json()
    assert done["status"] == "COMPLETED" and "Paid 50.00 more" in done["payments"][0]["detail"]
    extra = shop.owner.get("/api/v1/commerce/till-payments/").json()["payments"]
    assert [(row["code"], D(row["used_amount"])) for row in extra] == [("SKF6666666", D("300.00"))]


def test_a_paybill_payment_naming_the_checkout_pays_it_by_itself(shop):
    MpesaExpressSetup.objects.filter(pk=shop.till.pk).update(kind=MpesaExpressSetup.PAYBILL, till_number="")
    checkout = charge(shop.amina, shop)
    notice(shop, "SKG7777777", 300, TransactionType="Pay Bill", BillRefNumber=checkout["number"].lower())
    assert shop.amina.get(f"{CHECKOUTS}{checkout['id']}/").json()["status"] == "COMPLETED"


def answer(push, paid=True, receipt="SKH8888888"):
    with organization_context(push.organization):
        metadata = {"Item": [{"Name": "MpesaReceiptNumber", "Value": receipt}, {"Name": "Amount", "Value": int(push.amount)}]}
        mpesa_express.apply_result(push, "0" if paid else "1032", metadata=metadata if paid else None)


def prompt(shop, client, checkout):
    with mock.patch.object(mpesa_express, "_request", side_effect=[{"access_token": "tok"}, {"ResponseCode": "0", "CheckoutRequestID": f"ws_{uuid4().hex[:8]}",
                                                                                              "CustomerMessage": "Sent"}]), \
            mock.patch.object(mpesa_express, "ready", return_value=True):
        response = pay(client, checkout, method="PROMPT", phone="0712345678")
    assert response.status_code == 201, response.content
    with organization_context(shop.org):
        return StkPush.objects.latest("pk")


def test_a_prompt_pays_its_own_checkout_and_its_till_notice_is_not_offered_again(shop):
    checkout = charge(shop.amina, shop)
    push = prompt(shop, shop.amina, checkout)
    assert shop.amina.get(f"{CHECKOUTS}{checkout['id']}/").json()["status"] == "AWAITING"
    answer(push)
    done = shop.amina.get(f"{CHECKOUTS}{checkout['id']}/").json()
    assert done["status"] == "COMPLETED" and done["payments"][0]["reference"] == "SKH8888888"
    notice(shop, "SKH8888888", 300)  # Safaricom's till notice of the very same payment
    other = charge(shop.brian, shop)
    assert shop.brian.get(f"{CHECKOUTS}{other['id']}/").json()["till_payments"] == []


def test_a_payment_after_the_customer_left_is_kept_for_a_refund_never_lost(shop):
    checkout = charge(shop.amina, shop)
    push = prompt(shop, shop.amina, checkout)
    assert shop.amina.post(f"{CHECKOUTS}{checkout['id']}/cancel/", {"reason": "Customer left"}, format="json").json()["status"] == "CANCELLED"
    answer(push, receipt="SKI9999999")
    with organization_context(shop.org):
        late = IncomingMpesaPayment.objects.get(transaction_id="SKI9999999")
        assert late.status == "UNMATCHED" and "was closed" in late.note and not Sale.objects.exists()


def test_money_received_means_only_a_manager_cancels_and_it_returns_to_the_unmatched_payments(shop):
    checkout = charge(shop.amina, shop, quantity=2)
    notice(shop, "SKJ1010101", 300)
    pay(shop.amina, checkout, method="TILL", code="SKJ1010101")
    refused = shop.amina.post(f"{CHECKOUTS}{checkout['id']}/cancel/", {"reason": "Changed mind"}, format="json")
    assert refused.status_code == 403
    assert shop.owner.post(f"{CHECKOUTS}{checkout['id']}/cancel/", {"reason": "Changed mind"}, format="json").json()["status"] == "CANCELLED"
    row = shop.owner.get("/api/v1/commerce/till-payments/").json()["payments"][0]
    assert row["status"] == "UNMATCHED" and "refund the customer" in row["note"]
    settled = shop.owner.post(f"/api/v1/commerce/till-payments/{row['id']}/settle/", {"note": "Refunded by M-Pesa"}, format="json").json()
    assert settled["status"] == "SETTLED"


def test_stock_sold_out_while_the_customer_paid_keeps_the_money_and_the_sale_waits(shop):
    checkout = charge(shop.amina, shop, quantity=8)
    sold = shop.brian.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": shop.charger.pk, "quantity": 5}], "payment_method": "CASH"}, format="json")
    assert sold.status_code == 201
    paid = pay(shop.amina, checkout, method="CASH", cash_given="2400").json()
    assert paid["status"] == "PAID" and "could not be made" in paid["problem"] and "receipt" not in paid
    with organization_context(shop.org):
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-2", received_at=timezone.now(),
                               lines=[{"variant_id": shop.charger.pk, "received_quantity": "5", "unit_cost": "160"}], user=shop.org.owner)
    done = shop.amina.post(f"{CHECKOUTS}{checkout['id']}/retry/", format="json").json()
    assert done["status"] == "COMPLETED" and in_stock(shop) == 2


def test_cash_and_mpesa_together_pay_one_sale(shop):
    checkout = charge(shop.amina, shop, quantity=2)
    pay(shop.amina, checkout, method="CASH", amount="400", cash_given="400")
    notice(shop, "SKK1212121", 200)
    done = pay(shop.amina, checkout, method="TILL", code="SKK1212121").json()
    assert done["status"] == "COMPLETED" and [p["method"] for p in done["payments"]] == ["CASH", "TILL"]
    with organization_context(shop.org):
        assert sorted((p.method, p.amount) for p in Payment.objects.all()) == [("CASH", D("400.00")), ("MPESA", D("200.00"))]


def test_a_cashier_cannot_see_or_take_payment_on_another_cashiers_checkout(shop):
    checkout = charge(shop.amina, shop)
    assert shop.brian.get(f"{CHECKOUTS}{checkout['id']}/").status_code == 403
    assert pay(shop.brian, checkout, method="CASH", cash_given="300").status_code == 403
    assert shop.brian.get(CHECKOUTS).json()["checkouts"] == []
    assert [row["id"] for row in shop.owner.get(CHECKOUTS).json()["checkouts"]] == [checkout["id"]]  # a manager sees the branch


def test_only_a_named_customer_can_owe_and_a_repeated_charge_is_one_checkout(shop):
    checkout = charge(shop.amina, shop)
    refused = pay(shop.amina, checkout, method="OWED")
    assert refused.status_code == 400 and "Choose the customer" in str(refused.json())
    body = {"items": [{"variant_id": shop.charger.pk, "quantity": 1}], "idempotency_key": "same-tap"}
    first = shop.amina.post(CHECKOUTS, body, format="json").json()
    assert shop.amina.post(CHECKOUTS, body, format="json").json()["id"] == first["id"]


def test_an_unpaid_basket_left_alone_expires(shop):
    checkout = charge(shop.amina, shop)
    with organization_context(shop.org):
        Checkout.objects.filter(pk=checkout["id"]).update(created_at=timezone.now() - timedelta(hours=1))
    assert shop.amina.get(CHECKOUTS).json()["checkouts"] == []
    with organization_context(shop.org):
        assert Checkout.objects.get(pk=checkout["id"]).status == "EXPIRED"
