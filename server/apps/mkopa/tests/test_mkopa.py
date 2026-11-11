"""M-KOPA phones: plans and the commission each earns, phones in hand, sales, and commission counting only when paid."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.accounting.models import CashEntry, JournalLine
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription
from apps.tenancy.permissions import employee_permission

pytestmark = pytest.mark.django_db
X30 = {"name": "X30", "plans": [{"deposit": "3899", "daily_payment": "93", "days": 365, "commission": "1200"},
                                {"deposit": "5999", "daily_payment": "130", "days": 180, "commission": "1500"}]}


def business(modules=("pos", "inventory", "mkopa")):
    owner = User.objects.create_user(f"owner{Organization.objects.count()}", password="Safe-pass-1848")
    org = Organization.objects.create(name="Shop", slug=f"shop-{Organization.objects.count()}", owner=owner, enabled_modules=list(modules))
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
    client = APIClient()
    client.force_login(owner)
    return org, client


def key(n=[0]):
    n[0] += 1
    return f"k{n[0]}"


def overview(client):
    response = client.get("/api/v1/mkopa/")
    assert response.status_code == 200, response.content
    return response.json()


def test_a_phone_with_two_plans_shows_what_the_customer_pays_and_the_commission_each_earns():
    org, client = business()
    assert client.post("/api/v1/mkopa/phones/", X30, format="json").status_code == 201
    assert client.post("/api/v1/mkopa/phones/", {"name": "X4", "plans": [{"deposit": "2999", "daily_payment": "60", "days": 365, "commission": "900"}]},
                       format="json").status_code == 201
    phones = {p["name"]: p for p in overview(client)["phones"]}
    plans = phones["X30"]["plans"]
    assert [(Decimal(p["total_price"]), Decimal(p["commission"])) for p in plans] == [(Decimal("37844"), Decimal("1200")), (Decimal("29399"), Decimal("1500"))]
    assert len(phones["X4"]["plans"]) == 1
    again = client.post("/api/v1/mkopa/phones/", {"name": "x30", "plans": X30["plans"]}, format="json")
    assert again.status_code == 400 and "already" in str(again.json())


def test_sales_earn_the_plans_commission_which_counts_as_profit_only_when_mkopa_pays_it():
    org, client = business()
    client.post("/api/v1/mkopa/phones/", X30, format="json")
    phone = overview(client)["phones"][0]
    cheap, quick = phone["plans"]
    client.post("/api/v1/mkopa/stock/", {"phone": phone["id"], "quantity": 2, "kind": "RECEIVED", "idempotency_key": key()}, format="json")
    for plan, imei in [(cheap, "351111"), (quick, "352222")]:
        sold = client.post("/api/v1/mkopa/sales/", {"plan": plan["id"], "customer_name": "Mary Achieng", "imei": imei, "idempotency_key": key()}, format="json")
        assert sold.status_code == 201, sold.content
    none_left = client.post("/api/v1/mkopa/sales/", {"plan": cheap["id"], "customer_name": "John Kamau", "idempotency_key": key()}, format="json")
    assert none_left.status_code == 400 and "no X30 in hand" in str(none_left.json())

    data = overview(client)
    assert data["phones"][0]["in_hand"] == 0 and data["phones"][0]["sold"] == 2
    summary = data["summary"]
    assert Decimal(summary["commission_earned"]) == 2700 and Decimal(summary["commission_owed"]) == 2700 and Decimal(summary["commission_paid"]) == 0
    with organization_context(org):
        assert not JournalLine.objects.filter(account__code="4050").exists()  # owed, not yet profit

    paid = client.post("/api/v1/mkopa/commission/", {"amount": "2000", "method": "MPESA", "reference": "tk12ab", "idempotency_key": key()}, format="json")
    assert paid.status_code == 201, paid.content
    summary = overview(client)["summary"]
    assert Decimal(summary["commission_paid"]) == 2000 and Decimal(summary["commission_owed"]) == 700
    with organization_context(org):
        entry = CashEntry.objects.get(source_key__startswith="mkopa:")
        assert (entry.business_unit, entry.kind, entry.amount) == ("MKOPA", "INCOME", Decimal("2000"))
        income = sum(line.credit - line.debit for line in JournalLine.objects.filter(account__code="4050"))
        cash = sum(line.debit - line.credit for line in JournalLine.objects.filter(account__code="1020"))
        assert income == 2000 and cash == 2000
    dashboard = client.get("/api/v1/inventory/dashboard/").json()
    unit = next(u for u in dashboard["business_units"] if u["key"] == "MKOPA")
    assert unit["enabled"] and Decimal(unit["all_time"]["revenue"]) == 2000

    # Undone: the income and the money both come back out, and M-KOPA owes it again.
    undone = client.post(f"/api/v1/mkopa/commission/{paid.json()['id']}/undo/", {"reason": "Typed the wrong amount"}, format="json")
    assert undone.status_code == 200, undone.content
    assert Decimal(overview(client)["summary"]["commission_owed"]) == 2700
    with organization_context(org):
        assert sum(line.credit - line.debit for line in JournalLine.objects.filter(account__code="4050")) == 0
        from apps.accounting.services import reverse
        other = client.post("/api/v1/mkopa/commission/", {"amount": "500", "method": "CASH", "idempotency_key": key()}, format="json").json()
        with pytest.raises(Exception, match="M-KOPA"):
            reverse(entry=CashEntry.objects.get(mkopa_commission__pk=other["id"]), user=None, reason="x")


def test_changing_a_plan_keeps_what_earlier_sales_earned_and_an_undone_sale_puts_the_phone_back_in_hand():
    org, client = business()
    client.post("/api/v1/mkopa/phones/", X30, format="json")
    phone = overview(client)["phones"][0]
    plan = phone["plans"][0]
    sale = client.post("/api/v1/mkopa/sales/", {"plan": plan["id"], "customer_name": "Mary Achieng", "idempotency_key": key()}, format="json").json()
    changed = client.patch(f"/api/v1/mkopa/phones/{phone['id']}/", {"plans": [{**plan, "commission": "1000"}]}, format="json")
    assert changed.status_code == 200, changed.content
    data = overview(client)
    assert len(data["phones"][0]["plans"]) == 1 and len(data["phones"][0]["old_plans"]) == 1  # the 5999 plan stopped, kept for its sales
    assert Decimal(data["phones"][0]["plans"][0]["commission"]) == 1000 and Decimal(data["sales"][0]["commission"]) == 1200
    assert client.post(f"/api/v1/mkopa/sales/{sale['id']}/undo/", {"reason": "Customer changed their mind"}, format="json").status_code == 200
    assert Decimal(overview(client)["summary"]["commission_earned"]) == 0


def test_an_employee_sells_but_the_commission_and_plans_are_the_owners():
    pages = ["mkopa"]
    assert employee_permission("mkopa.add_mkopasale", pages) and employee_permission("mkopa.view_mkopaphone", pages)
    assert employee_permission("mkopa.add_mkopastock", pages)
    for owners in ["mkopa.view_mkopacommission", "mkopa.add_mkopacommission", "mkopa.change_mkopaphone", "mkopa.add_mkopaphone",
                   "mkopa.change_mkopasale"]:
        assert not employee_permission(owners, pages)
    assert not employee_permission("mkopa.add_mkopasale", ["sales"])


def test_the_tool_must_be_on():
    org, client = business(modules=("pos", "inventory"))
    assert client.get("/api/v1/mkopa/").status_code == 403


def test_the_owner_turns_mkopa_on_in_settings_and_it_is_never_on_by_default():
    from apps.tenancy.models import default_modules
    assert "mkopa" not in default_modules()
    org, client = business(modules=("pos", "inventory", "services", "customers"))
    org.business_model = "MIXED"
    org.save(update_fields=["business_model"])
    saved = client.patch("/api/v1/tenancy/settings/", {"enabled_modules": ["pos", "inventory", "services", "customers", "mkopa"]}, format="json")
    assert saved.status_code == 200, saved.content
    org.refresh_from_db()
    assert "mkopa" in org.enabled_modules
    assert client.get("/api/v1/mkopa/").status_code == 200
