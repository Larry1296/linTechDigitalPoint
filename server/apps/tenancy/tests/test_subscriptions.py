"""Free first month on the chosen plan, M-Pesa renewals, what pauses when a subscription ends, and the platform's view."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.tenancy import billing
from apps.tenancy.models import Organization, OrganizationSubscription, SubscriptionPayment, SubscriptionPlan

pytestmark = pytest.mark.django_db
EVERYTHING = ["inventory", "locations", "services", "pos", "customers", "expenses", "mpesa", "reports", "branches", "staff"]
BASIC = ["inventory", "services", "pos", "customers", "expenses", "mpesa"]


def signed_in(username, superuser=False):
    user = User.objects.create_user(username, password="Safe-pass-1848", is_superuser=superuser, is_staff=superuser)
    client = APIClient()
    client.force_login(user)
    return client


def new_business(client, plan="BASIC", name="Wanjiru Traders", modules=None):
    # A Basic business can only be set up with Basic tools; the platform owner's own business gets every tool.
    modules = modules or (BASIC if plan == "BASIC" else EVERYTHING)
    response = client.post("/api/v1/tenancy/create/", {"name": name, "business_model": "MIXED", "enabled_modules": modules, "plan": plan}, format="json")
    assert response.status_code == 201, response.content
    return Organization.objects.select_related("subscription__plan").get(pk=response.json()["id"])


def end_subscription(organization):
    OrganizationSubscription.objects.filter(organization=organization).update(ends_at=timezone.now() - timedelta(minutes=1))


def test_the_two_plans_exist_with_their_prices():
    public = APIClient().get("/api/v1/tenancy/plans/").json()
    assert [(p["code"], p["price"]) for p in public["plans"]] == [("BASIC", "500.00"), ("PRO", "1000.00")] and public["trial_days"] == 30
    assert [(p.code, p.price) for p in SubscriptionPlan.objects.exclude(code="").order_by("sort_order")] == [("BASIC", Decimal("500.00")), ("PRO", Decimal("1000.00"))]


def test_a_new_business_gets_a_free_month_on_the_plan_it_chose_and_basic_hides_pro_tools():
    owner = signed_in("owner")
    organization = new_business(owner, "BASIC")
    view = billing.state(organization)
    assert (view["status"], view["plan"], view["days_left"], view["ended"]) == ("TRIAL", "BASIC", 30, False)
    me = owner.get("/api/v1/auth/me/").json()["organization"]
    assert me["subscription"]["plan"] == "BASIC"
    assert "reports" not in me["enabled_modules"] and "inventory" in me["enabled_modules"]
    assert owner.get("/api/v1/accounting/ledger/reports/").status_code == 403


def test_the_platform_owners_own_business_is_pro_forever_with_every_tool():
    admin = signed_in("platform-owner", superuser=True)
    organization = new_business(admin, "BASIC", name="LinTechDigitalPoint", modules=EVERYTHING)
    view = billing.state(organization)
    assert (view["status"], view["plan"], view["complimentary"], view["ends_at"]) == ("ACTIVE", "PRO", True, None)
    end_subscription(organization)  # even an end date in the past never pauses it
    organization.refresh_from_db()
    assert billing.modules_for(Organization.objects.select_related("subscription__plan").get(pk=organization.pk)) == set(EVERYTHING)
    assert admin.post("/api/v1/tenancy/billing/pay/", {"plan": "PRO", "phone": "0712345678"}, format="json").status_code == 400


def test_an_ended_subscription_pauses_most_tools_but_keeps_counter_sales():
    owner = signed_in("owner")
    organization = new_business(owner, "PRO")
    end_subscription(organization)
    me = owner.get("/api/v1/auth/me/").json()["organization"]
    assert me["subscription"]["status"] == "EXPIRED" and me["subscription"]["ended"]
    assert sorted(me["enabled_modules"]) == ["customers", "inventory", "pos", "services"]
    assert owner.get("/api/v1/accounting/ledger/reports/").status_code == 403                   # accounting paused
    receive = owner.post("/api/v1/inventory/receive/", {}, format="json")                       # stock receiving paused
    assert receive.status_code == 403 and receive.json()["code"] == "subscription_ended"
    assert owner.post("/api/v1/commerce/pos/complete/", {"items": []}, format="json").status_code == 400  # reaches the sale rules
    assert owner.patch("/api/v1/tenancy/settings/", {"name": "x"}, format="json").status_code == 403
    assert owner.get("/api/v1/tenancy/billing/").status_code == 200                            # can always renew


@pytest.fixture
def simulated(settings):
    settings.DEBUG, settings.MPESA_MODE = True, "simulate"


def test_paying_by_mpesa_after_the_free_month_starts_a_new_paid_month(simulated):
    owner = signed_in("owner")
    organization = new_business(owner, "BASIC")
    trial_end = organization.subscription.ends_at
    sent = owner.post("/api/v1/tenancy/billing/pay/", {"plan": "BASIC", "phone": "0712 345 678"}, format="json")
    assert sent.status_code == 201, sent.content
    assert (sent.json()["status"], sent.json()["phone"], sent.json()["amount"]) == ("PENDING", "254712345678", "500.00")
    assert owner.post("/api/v1/tenancy/billing/pay/", {"plan": "PRO", "phone": "0712345678"}, format="json").status_code == 409
    SubscriptionPayment.objects.filter(pk=sent.json()["id"]).update(created_at=timezone.now() - timedelta(seconds=10))
    done = owner.get(f"/api/v1/tenancy/billing/payments/{sent.json()['id']}/").json()
    assert done["status"] == "PAID" and done["receipt_number"].startswith("SIM")
    organization.subscription.refresh_from_db()
    assert organization.subscription.status == "ACTIVE"
    assert organization.subscription.ends_at == trial_end + timedelta(days=30)  # the free month is kept


def test_period_rules_for_renewing_upgrading_and_returning():
    basic, pro = SubscriptionPlan.objects.get(code="BASIC"), SubscriptionPlan.objects.get(code="PRO")
    now = timezone.now()
    running = OrganizationSubscription(status="ACTIVE", plan=basic, ends_at=now + timedelta(days=10))
    assert billing.new_period_end(running, basic, now) == now + timedelta(days=40)            # renew: add a month
    assert billing.new_period_end(running, pro, now) == now + timedelta(days=35)              # upgrade: 10 Basic days = 5 Pro days
    ended = OrganizationSubscription(status="ACTIVE", plan=basic, ends_at=now - timedelta(days=3))
    assert billing.new_period_end(ended, pro, now) == now + timedelta(days=30)                # back after it ended: from today


@pytest.fixture
def daraja(settings):
    settings.MPESA_MODE, settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET = "sandbox", "key", "secret"
    settings.MPESA_SHORTCODE, settings.MPESA_PASSKEY = "174379", "passkey"
    settings.MPESA_CALLBACK_BASE_URL, settings.MPESA_CALLBACK_TOKEN = "https://platform.example", "long-secret"


def callback(checkout, code=0, amount="1000", receipt="QKJ1ABC23D"):
    return {"Body": {"stkCallback": {"MerchantRequestID": "m", "CheckoutRequestID": checkout, "ResultCode": code, "ResultDesc": "done",
            "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt}]}}}}


def test_the_mpesa_prompt_and_its_callback_activate_the_plan_once(daraja):
    owner = signed_in("owner")
    organization = new_business(owner, "BASIC")
    replies = [{"access_token": "t"}, {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_1", "MerchantRequestID": "m", "CustomerMessage": "Sent"}]
    with mock.patch.object(billing, "_request", side_effect=replies) as request:
        sent = owner.post("/api/v1/tenancy/billing/pay/", {"plan": "PRO", "phone": "+254 712 345 678"}, format="json")
    assert sent.status_code == 201, sent.content
    push = request.call_args_list[1].args[1]
    assert (push["Amount"], push["PhoneNumber"], push["BusinessShortCode"]) == (1000, "254712345678", "174379")
    assert push["CallBackURL"] == "https://platform.example/api/v1/tenancy/billing/mpesa/callback/long-secret/"
    anonymous = APIClient()
    assert anonymous.post("/api/v1/tenancy/billing/mpesa/callback/wrong/", callback("ws_CO_1"), format="json").status_code == 403
    assert anonymous.post("/api/v1/tenancy/billing/mpesa/callback/long-secret/", callback("ws_CO_1"), format="json").json()["ResultCode"] == 0
    anonymous.post("/api/v1/tenancy/billing/mpesa/callback/long-secret/", callback("ws_CO_1"), format="json")  # repeated delivery
    payment = SubscriptionPayment.objects.get()
    organization.subscription.refresh_from_db()
    assert (payment.status, payment.receipt_number, organization.subscription.plan.code) == ("PAID", "QKJ1ABC23D", "PRO")
    assert organization.subscription.ends_at.date() == (timezone.now() + timedelta(days=60)).date()


def test_a_cancelled_or_short_payment_does_not_activate(daraja):
    owner = signed_in("owner")
    organization = new_business(owner, "BASIC")
    for checkout, body in [("ws_CO_2", callback("ws_CO_2", code=1032)), ("ws_CO_3", callback("ws_CO_3", amount="10"))]:
        SubscriptionPayment.objects.filter(status="PENDING").delete()
        SubscriptionPayment.objects.create(organization=organization, plan=SubscriptionPlan.objects.get(code="PRO"), amount=1000, checkout_request_id=checkout)
        APIClient().post("/api/v1/tenancy/billing/mpesa/callback/long-secret/", body, format="json")
    assert list(SubscriptionPayment.objects.order_by("pk").values_list("status", flat=True)) == ["CANCELLED", "FAILED"]
    organization.subscription.refresh_from_db()
    assert (organization.subscription.status, organization.subscription.plan.code) == ("TRIAL", "BASIC")


def test_without_mpesa_set_up_the_owner_is_told_clearly():
    owner = signed_in("owner")
    new_business(owner)
    response = owner.post("/api/v1/tenancy/billing/pay/", {"plan": "BASIC", "phone": "0712345678"}, format="json")
    assert response.status_code == 503 and "not set up" in response.json()["detail"]
    assert owner.get("/api/v1/tenancy/billing/").json()["payment_methods"] == []


def test_only_the_platform_owner_sees_every_business_and_manages_subscriptions():
    owner = signed_in("owner")
    organization = new_business(owner, "BASIC")
    assert owner.get("/api/v1/tenancy/platform-admin/overview/").status_code == 403
    admin = signed_in("platform-owner", superuser=True)
    overview = admin.get("/api/v1/tenancy/platform-admin/overview/").json()
    assert overview["summary"]["trial"] == 1 and overview["businesses"][0]["owner"]["username"] == "owner"
    path = f"/api/v1/tenancy/platform-admin/businesses/{organization.pk}/"
    recorded = admin.post(path, {"plan": "PRO", "amount": "1000", "receipt_number": "CASH-1"}, format="json")
    assert recorded.status_code == 201, recorded.content
    assert recorded.json()["subscription"]["plan"] == "PRO" and recorded.json()["total_paid"] == "1000.00"
    suspended = admin.patch(path, {"status": "SUSPENDED", "note": "Asked to pause"}, format="json").json()
    assert suspended["subscription"]["ended"]
    assert admin.patch(path, {"extend_days": 7}, format="json").json()["subscription"]["status"] == "ACTIVE"
    plan = SubscriptionPlan.objects.get(code="BASIC")
    assert admin.patch(f"/api/v1/tenancy/platform-admin/plans/{plan.pk}/", {"price": "600"}, format="json").json()["price"] == "600.00"


def test_a_basic_business_cannot_switch_on_pro_tools_in_settings():
    owner = signed_in("owner")
    organization = new_business(owner, "BASIC")
    Organization.objects.filter(pk=organization.pk).update(enabled_modules=["inventory", "pos", "reports"])  # chosen at set-up
    data = owner.get("/api/v1/tenancy/settings/").json()
    assert "reports" not in data["plan_modules"] and "inventory" in data["plan_modules"]
    refused = owner.patch("/api/v1/tenancy/settings/", {"enabled_modules": ["inventory", "pos", "reports", "staff", "branches"]}, format="json")
    assert refused.status_code == 400 and "Branches, Staff need the Pro plan" in str(refused.json())
    kept = owner.patch("/api/v1/tenancy/settings/", {"enabled_modules": ["inventory", "pos", "reports", "customers"]}, format="json")
    assert kept.status_code == 200, kept.content  # an earlier choice is kept; Customers is in Basic
    OrganizationSubscription.objects.filter(organization=organization).update(plan=SubscriptionPlan.objects.get(code="PRO"))
    assert owner.patch("/api/v1/tenancy/settings/", {"enabled_modules": ["inventory", "pos", "staff"]}, format="json").status_code == 200
