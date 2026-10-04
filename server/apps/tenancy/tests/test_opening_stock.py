"""Stock the owner already has on hand is entered as opening stock: owner's capital, never a purchase or supplier debt."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db.models import Sum
from rest_framework.test import APIClient

from apps.accounting.models import JournalLine, SupplierPurchase
from apps.inventory.models import StockBalance
from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def shop(plan, sector, modules):
    client = APIClient()
    client.force_login(User.objects.create_user(f"owner-{plan}", password="Safe-pass-1848"))
    response = client.post("/api/v1/tenancy/create/", {"name": f"Shop {plan}", "business_model": "GOODS", "sector": sector, "plan": plan,
                                                       "enabled_modules": modules, "starter_categories": ["Vegetables", "Fruits"]}, format="json")
    assert response.status_code == 201, response.content
    return client, Organization.objects.get(pk=response.json()["id"])


def test_a_shop_without_shelves_adds_the_stock_it_already_has_as_opening_stock():
    client, organization = shop("BASIC", "mama_mboga", ["inventory", "pos", "expenses"])
    categories = client.get("/api/v1/inventory/categories/available/").json()
    assert {c["name"]: c["available"] for c in categories} == {"Fruits": True, "Vegetables": True}  # no rack needed
    vegetables = next(c["id"] for c in categories if c["name"] == "Vegetables")
    created = client.post("/api/v1/catalog/products/create-with-stock/", {"name": "Sukuma wiki", "category_id": vegetables, "sku": "SUKUMA",
        "selling_price": "20", "opening_quantity": "50", "opening_unit_cost": "12"}, format="json")
    assert created.status_code == 201, created.content
    with organization_context(organization):
        assert StockBalance.objects.aggregate(q=Sum("quantity"))["q"] == 50
        lines = {line.account.code: (line.debit, line.credit) for line in JournalLine.objects.select_related("account")}
        assert lines == {"1200": (Decimal("600.00"), 0), "3000": (0, Decimal("600.00"))}  # stock value against owner's capital
        assert not SupplierPurchase.objects.exists()


def test_a_shop_that_uses_shelves_still_places_categories_on_racks():
    client, _ = shop("PRO", "electronics", ["inventory", "locations", "pos"])
    assert all(not c["available"] for c in client.get("/api/v1/inventory/categories/available/").json())


def test_more_stock_found_for_an_existing_product_is_opening_stock_not_a_supplier_debt():
    from apps.inventory.models import StockLot
    client, organization = shop("BASIC", "duka", ["inventory", "pos"])
    category = client.get("/api/v1/inventory/categories/available/").json()[0]["id"]
    variant = client.post("/api/v1/catalog/products/create-with-stock/", {"name": "Omo 500g", "category_id": category, "sku": "OMO500",
                                                                         "selling_price": "150"}, format="json").json()["variant_id"]
    receive = lambda **extra: client.post("/api/v1/inventory/receipts/", {"document_status": "OPENING_BALANCE", **extra}, format="json")
    costed = receive(lines=[{"variant_id": variant, "received_quantity": "10", "unit_cost": "110", "placements": []}])
    assert costed.status_code == 201, costed.content
    unknown = receive(lines=[{"variant_id": variant, "received_quantity": "4", "uncosted": True, "placements": []}])
    assert unknown.status_code == 201, unknown.content
    refused = receive(lines=[{"variant_id": variant, "received_quantity": "1", "unit_cost": "110", "placements": []}], payment={"method": "CASH", "amount": "110"})
    assert refused.status_code == 400 and "no supplier to pay" in str(refused.json())
    with organization_context(organization):
        assert StockBalance.objects.aggregate(q=Sum("quantity"))["q"] == 14
        assert list(StockLot.objects.order_by("pk").values_list("cost_status", flat=True)) == ["COSTED", "UNCOSTED"]
        lines = {line.account.code: (line.debit, line.credit) for line in JournalLine.objects.select_related("account")}
        assert lines == {"1200": (Decimal("1100.00"), 0), "3000": (0, Decimal("1100.00"))}  # unknown-cost stock carries no value
        assert not SupplierPurchase.objects.exists()


def test_long_names_and_the_same_name_from_two_brands_are_both_accepted():
    client, organization = shop("BASIC", "electronics", ["inventory", "pos"])
    category = client.get("/api/v1/inventory/categories/available/").json()[0]["id"]
    add = lambda name, sku: client.post("/api/v1/catalog/products/create-with-stock/", {"name": name, "category_id": category, "sku": sku,
                                                                                    "selling_price": "300"}, format="json")
    assert add("ORAIMO ORIGINAL NORMAL FULL CHARGER WITH MICRO-USB CABLE 2.4A FAST CHARGING", "ORAIMO-LONG").status_code == 201
    assert add("Normal Full Charger", "ORAIMO-NFC").status_code == 201
    assert add("Normal Full Charger", "AMAYA-NFC").status_code == 201
