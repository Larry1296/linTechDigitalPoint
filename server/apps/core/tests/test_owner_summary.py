"""The first figures on the owner's dashboard: the business without M-Pesa, with every shilling of service income counted."""
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


def test_service_income_counts_before_running_costs_and_m_pesa_stays_out():
    owner = User.objects.create_user("summary-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Summary shop", slug="summary", owner=owner, enabled_modules=["inventory", "pos", "services", "mpesa", "reports", "expenses"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    with organization_context(org):
        from apps.accounting.models import ExpenseCategory
        from apps.cyber.services import create_service
        from apps.mpesa.models import MpesaOutlet
        from apps.mpesa.services import open_session, post_transaction
        store = Store.objects.create(name="Main")
        charging = create_service(owner, "Phone charging", "10")
        power = ExpenseCategory.objects.create(name="Electricity")
        outlet = MpesaOutlet.objects.create(store=store, display_name="Agent till")
        session = open_session(outlet=outlet, operator=owner, opening_cash="5000", opening_float="20000")
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="1000", user=owner, idempotency_key="d1")
    client.post("/api/v1/accounting/money-check/starting/", {"method": "CASH", "amount": "1000", "idempotency_key": "start"}, format="json")
    sold = client.post(f"/api/v1/cyber/income/{charging.variant.product_id}/", {"option_id": charging.pk, "quantity": "2",
                       "payment_method": "CASH", "idempotency_key": "c1"}, format="json")
    assert sold.status_code == 201
    spent = client.post("/api/v1/accounting/expenses/", {"category": power.pk, "business_unit": "CYBER", "amount": "50",
                        "description": "Tokens", "idempotency_key": "e1"}, format="json")
    assert spent.status_code == 201
    summary = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]
    for figures in (summary["today"], summary["all_time"]):
        assert {key: D(str(figures[key])) for key in ("products", "services", "sales", "cost", "expenses", "profit")} == {
            "products": D("0"), "services": D("20"), "sales": D("20"), "cost": D("0"), "expenses": D("50"), "profit": D("-30")}
    # 1000 starting + 20 from charging − 50 spent; the agency's 5000 cash and 20000 float are not the shop's money.
    assert D(str(summary["money"]["expected"])) == D("970")
    parts = {part["key"]: D(str(part["amount"])) for part in summary["money"]["parts"]}
    assert (parts["starting"], parts["received"], parts["expenses"]) == (D("1000"), D("20"), D("-50"))
    assert D(str(summary["customers_owe"])) == 0


def test_interest_earned_on_an_investment_is_not_products_sold():
    owner = User.objects.create_user("interest-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Interest shop", slug="interest", owner=owner, enabled_modules=["inventory", "pos", "reports", "expenses"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    with organization_context(org):
        from apps.accounting.investments import move, open_investment, record_statement
        Store.objects.create(name="Main")
        fund = open_investment(user=owner, name="CIC MMF")
        move(investment=fund, user=owner, kind="DEPOSIT", amount="1000", source="MPESA", key="dep")
        record_statement(investment=fund, user=owner, balance="1250", key="stmt")
    summary = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]["all_time"]
    assert (D(str(summary["products"])), D(str(summary["sales"])), D(str(summary["profit"]))) == (D("0"), D("0"), D("0"))
    report = client.get("/api/v1/accounting/reports/").json()
    assert D(str(report["totals"]["revenue"])) == 0
