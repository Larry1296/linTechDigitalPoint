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

    first = overview(client)["unpaid"][0]["id"]  # M-KOPA paid for the first phone only
    paid = client.post("/api/v1/mkopa/commission/", {"amount": "2000", "method": "MPESA", "reference": "tk12ab", "sales": [first],
                                                     "idempotency_key": key()}, format="json")
    assert paid.status_code == 201, paid.content
    summary = overview(client)["summary"]
    assert Decimal(summary["commission_paid"]) == 2000 and Decimal(summary["commission_owed"]) == 1500 and summary["unpaid_phones"] == 1
    with organization_context(org):
        entry = CashEntry.objects.get(source_key__startswith="mkopa:")
        assert (entry.business_unit, entry.kind, entry.amount) == ("MKOPA", "INCOME", Decimal("2000"))
        income = sum(line.credit - line.debit for line in JournalLine.objects.filter(account__code="4050"))
        cash = sum(line.debit - line.credit for line in JournalLine.objects.filter(account__code="1020"))
        assert income == 2000 and cash == 2000
    dashboard = client.get("/api/v1/inventory/dashboard/").json()
    unit = next(u for u in dashboard["business_units"] if u["key"] == "MKOPA")
    assert unit["enabled"] and Decimal(unit["all_time"]["revenue"]) == 2000
    # Business profit, like M-Pesa commission and interest: in "Profit so far, every part together".
    ever = dashboard["owner_summary"]["all_time"]
    assert Decimal(ever["mkopa_commission"]) == 2000 and Decimal(ever["profit"]) == 2000

    # Undone: the income and the money both come back out, and M-KOPA owes it again at the plan's commission.
    undone = client.post(f"/api/v1/mkopa/commission/{paid.json()['id']}/undo/", {"reason": "Typed the wrong amount"}, format="json")
    assert undone.status_code == 200, undone.content
    assert Decimal(overview(client)["summary"]["commission_owed"]) == 2700 and overview(client)["summary"]["unpaid_phones"] == 2
    with organization_context(org):
        assert sum(line.credit - line.debit for line in JournalLine.objects.filter(account__code="4050")) == 0
        from apps.accounting.services import reverse
        other = client.post("/api/v1/mkopa/commission/", {"amount": "500", "method": "CASH", "sales": [], "idempotency_key": key()}, format="json").json()
        with pytest.raises(Exception, match="M-KOPA"):
            reverse(entry=CashEntry.objects.get(mkopa_commission__pk=other["id"]), user=None, reason="x")


def test_a_phone_not_paid_for_yet_follows_its_plans_commission_and_an_undone_sale_puts_the_phone_back_in_hand():
    org, client = business()
    client.post("/api/v1/mkopa/phones/", X30, format="json")
    phone = overview(client)["phones"][0]
    plan = phone["plans"][0]
    sale = client.post("/api/v1/mkopa/sales/", {"plan": plan["id"], "customer_name": "Mary Achieng", "idempotency_key": key()}, format="json").json()
    changed = client.patch(f"/api/v1/mkopa/phones/{phone['id']}/", {"plans": [{**plan, "commission": "1000"}]}, format="json")
    assert changed.status_code == 200, changed.content
    data = overview(client)
    assert len(data["phones"][0]["plans"]) == 1 and len(data["phones"][0]["old_plans"]) == 1  # the 5999 plan stopped, kept for its sales
    assert Decimal(data["phones"][0]["plans"][0]["commission"]) == 1000 and Decimal(data["sales"][0]["commission"]) == 1000
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


def test_the_app_learns_each_plans_commission_from_mkopas_payments_and_uses_it_for_the_next_phones():
    org, client = business()
    blank = {"name": "X30", "plans": [{"deposit": "3899", "daily_payment": "93", "days": 365}, {"deposit": "5999", "daily_payment": "130", "days": 180}]}
    assert client.post("/api/v1/mkopa/phones/", blank, format="json").status_code == 201
    cheap, quick = overview(client)["phones"][0]["plans"]
    assert cheap["commission"] is None and cheap["commission_source"] is None  # not typed: waiting to be learned

    def sell(plan, times):
        for _ in range(times):
            client.post("/api/v1/mkopa/sales/", {"plan": plan["id"], "customer_name": "Mary Achieng", "idempotency_key": key()}, format="json")

    def pay(amount):
        response = client.post("/api/v1/mkopa/commission/", {"amount": amount, "method": "MPESA", "idempotency_key": key()}, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    sell(cheap, 4); sell(quick, 2)
    data = overview(client)
    assert data["summary"]["unknown_phones"] == 6 and Decimal(data["summary"]["commission_owed"]) == 0
    first = pay("7800")  # 4 × plan 1 + 2 × plan 2: not enough on its own to tell the two plans apart
    assert first["phones"] == 6 and overview(client)["phones"][0]["plans"][0]["commission"] is None
    sell(cheap, 1)
    pay("1200")  # 1 × plan 1: now both are known
    plans = overview(client)["phones"][0]["plans"]
    assert [(Decimal(p["commission"]), p["commission_source"], p["learned_from"]) for p in plans] == [
        (Decimal("1200"), "LEARNED", 2), (Decimal("1500"), "LEARNED", 1)]
    assert [(p["sold"], p["paid_phones"], Decimal(p["received"])) for p in plans] == [(5, 5, Decimal("6000")), (2, 2, Decimal("3000"))]

    sell(quick, 1)  # the next phone sold is expected to earn the learned commission
    data = overview(client)
    assert Decimal(data["summary"]["commission_owed"]) == 1500 and Decimal(data["sales"][0]["commission"]) == 1500
    paid_sale = next(s for s in data["sales"] if s["commission_paid"])
    refused = client.post(f"/api/v1/mkopa/sales/{paid_sale['id']}/undo/", {"reason": "Customer returned it"}, format="json")
    assert refused.status_code == 400 and "Undo that payment first" in str(refused.json())

    # A payment undone teaches nothing any more.
    client.post(f"/api/v1/mkopa/commission/{first['id']}/undo/", {"reason": "Wrong amount"}, format="json")
    plans = overview(client)["phones"][0]["plans"]
    assert Decimal(plans[0]["commission"]) == 1200 and plans[1]["commission"] is None


def test_commission_is_recorded_for_each_phone_specifically_and_teaches_each_plan_at_once():
    org, client = business()
    client.post("/api/v1/mkopa/phones/", {"name": "X30", "plans": [{"deposit": "3899", "daily_payment": "93", "days": 365},
                                                                   {"deposit": "5999", "daily_payment": "130", "days": 180}]}, format="json")
    cheap, quick = overview(client)["phones"][0]["plans"]
    for plan in (cheap, cheap, quick):
        client.post("/api/v1/mkopa/sales/", {"plan": plan["id"], "customer_name": "Mary Achieng", "idempotency_key": key()}, format="json")
    first, second, third = sorted(overview(client)["unpaid"], key=lambda sale: sale["id"])
    # M-KOPA paid two of the three phones, an amount for each; the third waits.
    paid = client.post("/api/v1/mkopa/commission/", {"method": "MPESA", "amounts": [{"sale": first["id"], "amount": "1200"},
                       {"sale": third["id"], "amount": "1450"}], "idempotency_key": key()}, format="json")
    assert paid.status_code == 201, paid.content
    row = paid.json()
    assert Decimal(row["amount"]) == 2650 and row["itemised"] and [Decimal(p["amount"]) for p in row["for_phones"]] == [1200, 1450]
    data = overview(client)
    by_id = {sale["id"]: sale for sale in data["sales"]}
    assert Decimal(by_id[first["id"]]["commission"]) == 1200 and Decimal(by_id[third["id"]]["commission"]) == 1450
    assert not by_id[second["id"]]["commission_paid"] and Decimal(by_id[second["id"]]["commission"]) == 1200  # learned from the first phone
    plans = data["phones"][0]["plans"]
    assert [(Decimal(p["commission"]), p["commission_source"]) for p in plans] == [(Decimal("1200"), "LEARNED"), (Decimal("1450"), "LEARNED")]
    assert Decimal(data["summary"]["commission_owed"]) == 1200

    mismatch = client.post("/api/v1/mkopa/commission/", {"method": "CASH", "amount": "999", "amounts": [{"sale": second["id"], "amount": "1200"}],
                                                         "idempotency_key": key()}, format="json")
    assert mismatch.status_code == 400 and "add up to 1,200.00" in str(mismatch.json())
    twice = client.post("/api/v1/mkopa/commission/", {"method": "CASH", "amounts": [{"sale": first["id"], "amount": "1200"}], "idempotency_key": key()}, format="json")
    assert twice.status_code == 400 and "already paid" in str(twice.json())
