"""A business made of parts (shop, cyber, M-Pesa agency) under one name: the owner says so at setup, names the parts,
and shares running costs between them; profit is the whole business's and the parts' contributions add up to it."""
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db
D = Decimal
ALL_PARTS = ["inventory", "pos", "services", "mpesa", "expenses", "reports"]


def owner_of(**setup):
    client = APIClient()
    client.force_login(User.objects.create_user(f"owner-{User.objects.count()}", password="Safe-pass-1848"))
    response = client.post("/api/v1/tenancy/create/", {"name": "LinTech Digital Point", "business_model": "MIXED", "sector": "cyber_shop",
                                                       "plan": "PRO", "enabled_modules": ALL_PARTS, **setup}, format="json")
    assert response.status_code == 201, response.content
    return client, response.json()


def expense(client, amount, **values):
    category = next((c for c in client.get("/api/v1/accounting/categories/").json() if c["name"] == "Rent"), None) \
        or client.post("/api/v1/accounting/categories/", {"name": "Rent"}, format="json").json()
    return client.post("/api/v1/accounting/expenses/", {"category": category["id"], "business_unit": "SHOP", "amount": amount,
                                                        "description": "October rent", "idempotency_key": uuid4().hex,
                                                        **values}, format="json")


def parts_of(client):
    data = client.get("/api/v1/inventory/dashboard/").json()
    return data, {part["key"]: part for part in data["unit_period"]}


def test_the_owner_says_the_business_has_parts_and_names_them():
    client, business = owner_of(structure="PARTS", part_names={"CYBER": "Cyber café", "MPESA": " "})
    assert business["structure"] == "PARTS"
    assert business["parts"] == [{"key": "SHOP", "name": "Shop"}, {"key": "CYBER", "name": "Cyber café"}, {"key": "MPESA", "name": "M-Pesa"}]
    data, parts = parts_of(client)
    assert data["has_parts"] is True and parts["CYBER"]["name"] == "Cyber café"
    # Renamed later in Settings.
    response = client.patch("/api/v1/tenancy/settings/", {"part_names": {"SHOP": "Accessories shop"}}, format="json")
    assert response.status_code == 200 and response.json()["part_names"]["SHOP"] == "Accessories shop"


def test_a_shared_cost_is_split_and_the_parts_add_up_to_the_whole_business():
    client, _ = owner_of(structure="PARTS")
    response = expense(client, "3000.01", split="EVEN")
    assert response.status_code == 201, response.content
    assert response.json()["shares"] == {"SHOP": "1000.01", "CYBER": "1000.00", "MPESA": "1000.00"}
    data, parts = parts_of(client)
    assert [D(str(parts[key]["expenses"])) for key in ("SHOP", "CYBER", "MPESA")] == [D("1000.01"), D("1000.00"), D("1000.00")]
    whole = D(str(data["period_summary"]["profit"]))
    assert whole == D("-3000.01") == sum(D(str(part["profit"])) for part in parts.values())
    today = next(point for point in data["unit_days"] if point["date"] == data["period_summary"]["end"])
    assert D(str(today["TOTAL_costs"])) == D("3000.01") and D(str(today["CYBER_costs"])) == D("1000.00")
    assert D(str(today["TOTAL_profit"])) == whole


def test_the_owner_enters_each_parts_share_and_they_must_make_the_whole():
    client, _ = owner_of(structure="PARTS")
    wrong = expense(client, "5000", split="AMOUNTS", shares={"SHOP": "3000", "CYBER": "1000"})
    assert wrong.status_code == 400 and "must make the whole 5,000.00" in str(wrong.json())
    right = expense(client, "5000", split="AMOUNTS", shares={"SHOP": "3000", "CYBER": "1500", "MPESA": "500"})
    assert right.status_code == 201 and right.json()["shares"] == {"SHOP": "3000.00", "CYBER": "1500.00", "MPESA": "500.00"}
    # All of it on one part is simply that part's cost, paid from its money.
    single = expense(client, "800", split="AMOUNTS", shares={"SHOP": "0", "CYBER": "800"})
    assert single.status_code == 201 and single.json()["shares"] == {} and single.json()["business_unit"] == "CYBER"
    # The agency's share is one of its running costs on the commission page.
    with organization_context(Organization.objects.get(name="LinTech Digital Point")):
        from apps.mpesa.commission import monthly_profit
        assert monthly_profit()[-1]["expenses"] == D("500.00")


def test_sharing_by_income_needs_some_income_first():
    client, _ = owner_of(structure="PARTS")
    response = expense(client, "1200", split="INCOME")
    assert response.status_code == 400 and "No part has earned anything in the last 30 days" in str(response.json())


def test_a_cancelled_shared_cost_leaves_every_part():
    client, _ = owner_of(structure="PARTS")
    shared = expense(client, "900", split="EVEN").json()
    assert client.post(f"/api/v1/accounting/expenses/{shared['id']}/cancel/", {"reason": "recorded twice"}, format="json").status_code == 200
    _, parts = parts_of(client)
    assert all(D(str(part["expenses"])) == 0 for part in parts.values())


def test_one_business_has_no_parts_to_share_costs_between():
    client, business = owner_of(structure="SINGLE", money_mode="SEPARATE_CASH")
    assert business["structure"] == "SINGLE"
    data, _ = parts_of(client)
    assert data["has_parts"] is False
    response = expense(client, "1000", split="EVEN")
    assert response.status_code == 400 and "Only a business with separate parts" in str(response.json())
    # A drawer for each part means nothing without parts.
    with organization_context(Organization.objects.get(name="LinTech Digital Point")):
        from apps.accounting.money_mode import separate_cash
        assert separate_cash() is False


def test_businesses_that_never_answered_keep_their_parts():
    client, business = owner_of()
    assert business["structure"] == "PARTS"  # three parts earn money


def test_with_a_drawer_for_each_part_the_chosen_drawer_pays_a_shared_cost():
    client, _ = owner_of(structure="PARTS", money_mode="SEPARATE_CASH")
    response = expense(client, "600", split="EVEN", business_unit="CYBER")
    assert response.status_code == 201 and response.json()["business_unit"] == "CYBER"
    one_drawer, _ = owner_of(structure="PARTS")
    response = expense(one_drawer, "600", split="AMOUNTS", shares={"SHOP": "100", "CYBER": "100", "MPESA": "400"}, business_unit="SHOP")
    assert response.status_code == 201, response.content
    assert response.json()["business_unit"] == "MPESA"  # all the money is together: the part carrying most of it pays
