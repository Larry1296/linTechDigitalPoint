"""Net worth on the dashboard: every figure from where the money really is, with the agency's live shift money."""
from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


def test_net_worth_adds_shop_money_live_agency_money_and_investments_less_what_is_owed():
    owner = User.objects.create_user("worth-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Worth shop", slug="worth", owner=owner, settings={"money_mode": "SEPARATE_CASH"})  # the agency keeps its own drawer
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    with organization_context(org):
        from apps.accounting.models import ExpenseCategory
        from apps.accounting.services import record_expense
        from apps.mpesa.models import MpesaOutlet
        from apps.mpesa.services import open_session, post_transaction
        store = Store.objects.create(name="Main")
        outlet = MpesaOutlet.objects.create(store=store, display_name="Agent till")
        session = open_session(outlet=outlet, operator=owner, opening_cash="5000", opening_float="20000")
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="1000", user=owner, idempotency_key="dep-1",
                         provider_reference="SJK9DEP001")
        record_expense(user=owner, category=ExpenseCategory.objects.create(name="Power"), unit="SHOP", method="CASH", amount="200",
                       description="Token", key="power", paid=False, due_date=timezone.localdate() + timedelta(days=7))
    client.post("/api/v1/accounting/money-check/starting/", {"method": "MPESA", "amount": "10000", "idempotency_key": "start"}, format="json")
    mmf = client.post("/api/v1/accounting/investments/", {"name": "CIC MMF", "annual_rate": "13"}, format="json").json()["id"]
    client.post(f"/api/v1/accounting/investments/{mmf}/move/", {"kind": "DEPOSIT", "amount": "3000", "source": "OWNER", "idempotency_key": "in"}, format="json")
    last_month = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
    client.post("/api/v1/mpesa/commission/", {"outlet": outlet.pk, "period": str(last_month), "amount": "500", "reference": "SJK9COM001",
                "settlement_method": "MPESA", "idempotency_key": "c1"}, format="json")
    worth = client.get("/api/v1/inventory/dashboard/").json()["net_worth"]
    groups = {g["key"]: g for g in worth["groups"]}
    till = next(i for i in groups["money"]["items"] if i["key"] == "shop-mpesa")
    assert D(str(till["amount"])) == D("10500")  # 10,000 starting plus the 500 commission kept there
    assert D(str(groups["money"]["amount"])) == D("10500")  # the owner's own money in the MMF is not the business's
    shift = groups["agency"]["items"][0]
    assert shift["state"] == "OPEN" and (D(str(shift["cash"])), D(str(shift["float"]))) == (D("6000"), D("19000"))
    assert (D(str(shift["opening_cash"])), D(str(shift["opening_float"]))) == (D("5000"), D("20000"))
    assert D(str(groups.get("investments", {"amount": 0})["amount"])) == 0 and D(str(groups["expenses"]["amount"])) == D("200")
    assert D(str(worth["owns"])) == D("35500") and D(str(worth["owes"])) == D("200") and D(str(worth["net_worth"])) == D("35300")
    assert worth["left_out"] == [] and len(worth["history"]) == 1 and D(str(worth["history"][0]["net_worth"])) == D("35300")
    # When the shift closes, the agency's money is what was counted at the close.
    with organization_context(org):
        from apps.mpesa.services import reconcile_session
        reconcile_session(session=session, user=owner, actual_cash="6000", actual_float="18900", reason="Float short by 100")
    shift = next(g for g in client.get("/api/v1/inventory/dashboard/").json()["net_worth"]["groups"] if g["key"] == "agency")["items"][0]
    assert shift["state"] == "CLOSED" and D(str(shift["amount"])) == D("24900")
