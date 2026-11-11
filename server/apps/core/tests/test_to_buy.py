"""The scratch list of things to buy: its own notes, never stock, money or the books."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.accounting.models import CashEntry, JournalEntry
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db


def business():
    owner = User.objects.create_user(f"owner{Organization.objects.count()}", password="Safe-pass-1848")
    org = Organization.objects.create(name="Shop", slug=f"shop-{Organization.objects.count()}", owner=owner, enabled_modules=["pos", "inventory"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
    client = APIClient()
    client.force_login(owner)
    return org, client


def test_the_list_works_out_each_lines_total_and_the_money_to_carry_without_touching_the_books():
    org, client = business()
    for item in [{"name": "Type-C cables", "count": "10", "unit_price": "150"}, {"name": "Printing paper", "count": "2", "unit": "reams"},
                 {"name": "Screen protectors", "count": "20", "unit_price": "40", "note": "Tecno and Samsung"}]:
        assert client.post("/api/v1/to-buy/", item, format="json").status_code == 201
    data = client.get("/api/v1/to-buy/").json()
    assert [(i["name"], i["total"] and Decimal(str(i["total"]))) for i in data["items"]] == [("Type-C cables", 1500), ("Printing paper", None), ("Screen protectors", 800)]
    assert data["left"] == 3 and Decimal(data["left_total"]) == 2300 and data["unpriced"] == 1
    cables = data["items"][0]["id"]
    data = client.patch(f"/api/v1/to-buy/{cables}/", {"count": "12"}, format="json").json()  # changing how many works it out again
    assert Decimal(data["left_total"]) == 2600
    data = client.patch(f"/api/v1/to-buy/{cables}/", {"bought": True}, format="json").json()
    assert data["items"][-1]["name"] == "Type-C cables" and Decimal(data["left_total"]) == 800 and Decimal(data["bought_total"]) == 1800
    assert client.post("/api/v1/to-buy/", {"name": " "}, format="json").status_code == 400
    assert client.post("/api/v1/to-buy/", {"name": "Glue", "count": "0"}, format="json").status_code == 400
    data = client.delete("/api/v1/to-buy/").json()
    assert [i["name"] for i in data["items"]] == ["Printing paper", "Screen protectors"] and Decimal(data["bought_total"]) == 0
    with organization_context(org):
        assert not CashEntry.objects.exists() and not JournalEntry.objects.exists()
    other_org, other = business()
    assert other.get("/api/v1/to-buy/").json()["items"] == []  # each business's own list


def test_a_line_leaves_the_list_once_the_item_is_received_into_stock():
    from apps.catalog.models import Category, Product, ProductVariant
    from apps.inventory.models import Movement
    org, client = business()
    with organization_context(org):
        category = Category.objects.create(name="Cables", slug="cables")
        cable = ProductVariant.objects.create(product=Product.objects.create(name="Type-C cable", slug="type-c", category=category), sku="TC1")
        charger = ProductVariant.objects.create(product=Product.objects.create(name="Charger", slug="charger", category=category), sku="CH1")
    client.post("/api/v1/to-buy/", {"name": "Cables for the shop", "variant": cable.pk, "count": "10"}, format="json")
    client.post("/api/v1/to-buy/", {"name": "charger", "count": "5"}, format="json")  # typed, no product picked
    client.post("/api/v1/to-buy/", {"name": "Printing paper"}, format="json")
    data = client.get("/api/v1/to-buy/").json()
    assert data["items"][0]["product"] == "Type-C cable"
    with organization_context(org):
        Movement.objects.create(variant=cable, quantity=10, movement_type="PURCHASE_RECEIPT", reference="R1")
        Movement.objects.create(variant=charger, quantity=-1, movement_type="SALE", reference="S1")  # a sale clears nothing
    assert [i["name"] for i in client.get("/api/v1/to-buy/").json()["items"]] == ["charger", "Printing paper"]
    with organization_context(org):
        Movement.objects.create(variant=charger, quantity=5, movement_type="OPENING_STOCK", reference="O1")
    assert [i["name"] for i in client.get("/api/v1/to-buy/").json()["items"]] == ["Printing paper"]
