"""Each part keeps its own money, even with one drawer: the M-Pesa agency's page and shift are the agency's cash and
float only, the shop's and cyber's money is on their own pages, and the dashboard brings together only their profit."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.services import complete_stock_receipt
from apps.mpesa.models import MpesaOutlet, MpesaSession
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def lintech():
    owner = User.objects.create_user("larry", password="Safe-pass-1848")
    org = Organization.objects.create(name="LinTech", slug="lintech", owner=owner, settings={"money_mode": "ONE_DRAWER"},
                                      enabled_modules=["inventory", "pos", "services", "mpesa", "expenses", "reports"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        store = Store.objects.create(name="Main")
        outlet = MpesaOutlet.objects.create(store=store, display_name="Agent line", agent_reference="123456")
        charger = ProductVariant.objects.create(product=Product.objects.create(name="Charger", slug="charger", category=Category.objects.create(name="Power", slug="power")),
                                                name="Standard", sku="CHG", selling_price=1000)
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-1", received_at=timezone.now() - timedelta(days=1),
                               lines=[{"variant_id": charger.pk, "received_quantity": "20", "unit_cost": "100"}], user=owner)
    client = APIClient()
    client.force_login(owner)
    return SimpleNamespace(org=org, outlet=outlet, charger=charger, client=client)


def sell(shop, price, method="CASH", code=""):
    response = shop.client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": shop.charger.pk, "quantity": 1, "unit_price": str(price)}],
                                "payment_method": method, "payment_reference": code}, format="json")
    assert response.status_code == 201, response.content


def open_shift(shop, cash, line, **extra):
    return shop.client.post("/api/v1/mpesa/sessions/", {"outlet": shop.outlet.pk, "opening_cash": str(cash), "opening_float": str(line), **extra}, format="json")


def test_the_agency_shift_counts_only_the_agencys_money(lintech):
    shop = lintech
    sell(shop, 1000)                          # cash in the drawer, the shop's
    sell(shop, 500, "MPESA", "SKA1111111")    # sent to the agent line, the shop's
    opened = open_shift(shop, 10000, 20000)   # the agency's own cash and float
    assert opened.status_code == 201, opened.content
    with organization_context(shop.org):
        shift = MpesaSession.objects.get()
        assert (shift.opening_cash, shift.opening_float) == (D("10000.00"), D("20000.00"))
        assert shift.business_cash_at_open is None
    assert shop.client.post("/api/v1/mpesa/transactions/", {"session": shift.pk, "transaction_type": "CUSTOMER_DEPOSIT", "amount": "2000",
                            "customer_phone": "0712345678", "customer_id_number": "12345678", "idempotency_key": "d1"}, format="json").status_code == 201
    sell(shop, 300)
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert "combined" not in board
    assert (D(str(board["cash"])), D(str(board["float"]))) == (D("12000.00"), D("18000.00"))
    # What was entered at opening is what the desk shows: the shop's sales are not in it.
    assert (D(str(board["in_operation"]["total"])), D(str(board["in_operation"]["opening"]))) == (D("30000.00"), D("30000.00"))
    closed = shop.client.post(f"/api/v1/mpesa/sessions/{shift.pk}/reconcile/", {"actual_cash": "12000", "actual_float": "18000"}, format="json").json()
    assert (D(closed["cash_variance"]), D(closed["float_variance"])) == (0, 0)
    assert open_shift(shop, 12000, 18000).status_code == 201


def test_sales_never_change_the_agencys_money(lintech):
    shop = lintech
    shift = open_shift(shop, 11000, 20000).json()
    sell(shop, 300)
    sell(shop, 200, "MPESA", "SKC3333333")
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert D(str(board["in_operation"]["total"])) == D("31000.00")
    outlet = shop.client.get("/api/v1/mpesa/outlets/").json()
    outlet = (outlet["results"] if isinstance(outlet, dict) else outlet)[0]
    assert D(str(outlet["money_in_operation"]["total"])) == D("31000.00") and "combined" not in outlet["money_in_operation"]
    home = shop.client.get("/api/v1/inventory/dashboard/").json()
    assert D(str(home["mpesa"]["in_operation"])) == D("31000.00") and "business_cash" not in home["mpesa"]
    shop.client.post(f"/api/v1/mpesa/sessions/{shift['id']}/reconcile/", {"actual_cash": "11000", "actual_float": "20000"}, format="json")
    sell(shop, 100)
    assert D(str(shop.client.get("/api/v1/inventory/dashboard/").json()["mpesa"]["in_operation"])) == D("31000.00")


def test_net_worth_keeps_the_shops_money_and_the_agencys_apart(lintech):
    shop = lintech
    sell(shop, 1000)
    open_shift(shop, 11000, 20000)
    sell(shop, 300)
    sell(shop, 200, "MPESA", "SKD4444444")
    groups = {g["key"]: g for g in shop.client.get("/api/v1/inventory/dashboard/").json()["net_worth"]["groups"]}
    assert D(str(groups["agency"]["amount"])) == D("31000.00")
    assert {item["method"]: D(str(item["amount"])) for item in groups["money"]["items"]} == {"CASH": D("1300.00"), "MPESA": D("200.00")}
    assert groups["money"]["label"] == "Shop money (drawer, till, bank)"


def test_the_shops_drawer_is_counted_in_the_money_check(lintech):
    shop = lintech
    sell(shop, 1000)
    checked = shop.client.post("/api/v1/accounting/money-check/", {"method": "CASH", "actual": "1000"}, format="json")
    assert checked.status_code == 201, checked.content
    assert shop.client.get("/api/v1/accounting/one-drawer/").status_code == 404


def test_each_sale_shows_its_parts_own_money_right_after_it(lintech):
    shop = lintech
    sell(shop, 1000)
    open_shift(shop, 11000, 20000)                     # the agency's, never in the shop's figure
    sell(shop, 300)
    sell(shop, 200, "MPESA", "SKF6666666")
    sales = shop.client.get("/api/v1/commerce/sales/").json()["results"]   # newest first
    assert [D(str(sale["held_after"])) for sale in sales] == [D("1500.00"), D("1300.00"), D("1000.00")]


def test_cyber_and_the_dashboard_show_revenue_since_the_start(lintech):
    shop = lintech
    sell(shop, 1000)
    board = shop.client.get("/api/v1/inventory/dashboard/").json()
    shop_part = next(unit for unit in board["business_units"] if unit["key"] == "SHOP")
    assert D(str(shop_part["all_time"]["revenue"])) == D("1000.00")
    assert "all_time" in shop.client.get("/api/v1/cyber/dashboard/").json()


def test_each_part_keeps_its_own_books(lintech):
    shop = lintech
    sell(shop, 1000)                                   # a charger bought at 100
    open_shift(shop, 11000, 20000)
    books = shop.client.get("/api/v1/inventory/parts/SHOP/").json()
    assert (D(str(books["all_time"]["revenue"])), D(str(books["all_time"]["cogs"])), D(str(books["all_time"]["profit"]))) == (D("1000.00"), D("100.00"), D("900.00"))
    assert books["count"] == 1 and books["months"] and D(str(books["money"]["amount"])) == D("1000.00")
    assert [(row["label"], D(str(row["amount"]))) for row in books["money"]["places"]] == [("Cash in the drawer", D("1000.00"))]
    agency = shop.client.get("/api/v1/inventory/parts/MPESA/").json()
    assert D(str(agency["money"]["amount"])) == D("31000.00")  # opened with 11,000 cash and 20,000 float, the agency's only
    assert [row["label"] for row in agency["money"]["places"]] == ["Agency cash", "Agency float"]
    assert shop.client.get("/api/v1/inventory/parts/NOPE/").status_code == 403


def test_float_or_cash_from_another_part_comes_out_of_that_parts_money(lintech):
    shop = lintech
    shop.client.patch("/api/v1/tenancy/settings/", {"money_mode": "SEPARATE_CASH"}, format="json")
    sell(shop, 1000)                                   # the shop's cash drawer: 1,000
    shift = open_shift(shop, 2000, 5000).json()
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert {row["value"]: D(str(row["available"])) for row in board["sources"]}["SHOP:CASH"] == D("1000.00")

    def add(kind, value, source, key):
        return shop.client.post("/api/v1/mpesa/transactions/", {"session": shift["id"], "transaction_type": kind, "amount": str(value),
                                                                 "paid_by": source, "idempotency_key": key}, format="json")
    assert add("FLOAT_TOPUP", 600, "SHOP:CASH", "t1").status_code == 201
    refused = add("CASH_REBALANCE", 500, "SHOP:CASH", "t2")          # only 400 left with the shop
    assert refused.status_code == 400 and "only 400.00" in str(refused.json())
    assert add("CASH_REBALANCE", 300, "OUTSIDE", "t3").status_code == 201  # the owner's pocket: no part goes down
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert (D(str(board["cash"])), D(str(board["float"]))) == (D("2300.00"), D("5600.00"))
    assert {row["value"]: D(str(row["available"])) for row in board["sources"]}["SHOP:CASH"] == D("400.00")
    # Reversed on the desk: the shop gets its money back.
    from apps.mpesa.models import MpesaTransaction
    with organization_context(shop.org):
        topup = MpesaTransaction.objects.get(idempotency_key="t1")
    assert shop.client.post(f"/api/v1/mpesa/transactions/{topup.pk}/reverse/", {"reason": "wrong", "idempotency_key": "r1"}, format="json").status_code in (200, 201)
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert {row["value"]: D(str(row["available"])) for row in board["sources"]}["SHOP:CASH"] == D("1000.00")
    assert D(str(board["float"])) == D("5000.00")
