"""One drawer and one agent line for the whole business: the M-Pesa shift counts all the money, and expects the agency's
part plus the business's own sales money (combined.py). Nothing is counted twice."""
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


def test_the_shift_counts_all_the_money_and_expects_the_sales_with_the_agency(lintech):
    shop = lintech
    sell(shop, 1000)                          # cash in the drawer, the shop's
    sell(shop, 500, "MPESA", "SKA1111111")    # sent to the agent line, the shop's
    # Counted: everything in the drawer and on the line. The agency's part is what the shop's money leaves.
    opened = open_shift(shop, 11000, 20500)
    assert opened.status_code == 201, opened.content
    with organization_context(shop.org):
        shift = MpesaSession.objects.get()
        assert (shift.opening_cash, shift.opening_float) == (D("10000.00"), D("20000.00"))
        assert (shift.business_cash_at_open, shift.business_line_at_open) == (D("1000.00"), D("500.00"))
    # During the shift: an agency deposit, a cash sale, rent paid from the drawer.
    assert shop.client.post("/api/v1/mpesa/transactions/", {"session": shift.pk, "transaction_type": "CUSTOMER_DEPOSIT", "amount": "2000",
                            "customer_phone": "0712345678", "customer_id_number": "12345678", "idempotency_key": "d1"}, format="json").status_code == 201
    sell(shop, 300)
    category = shop.client.post("/api/v1/accounting/categories/", {"name": "Rent"}, format="json").json()
    assert shop.client.post("/api/v1/accounting/expenses/", {"category": category["id"], "business_unit": "SHOP", "amount": "100", "description": "Water",
                            "idempotency_key": "water-1", "payment_method": "CASH"}, format="json").status_code == 201
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    combined = board["combined"]
    assert (D(str(board["cash"])), D(str(board["float"]))) == (D("12000.00"), D("18000.00"))  # the agency's part, as always
    assert (D(str(combined["business_cash"])), D(str(combined["business_line"]))) == (D("1200.00"), D("500.00"))
    lines = {row["label"]: (D(str(row["cash"])), D(str(row["line"]))) for row in combined["since_open"]}
    assert lines == {"Shop received from customers": (D("300.00"), D("0")), "Shop spent on running costs": (D("-100.00"), D("0"))}
    # Closing: the whole drawer (12,000 agency + 1,200 shop) and line (18,000 + 500) match; no difference.
    closed = shop.client.post(f"/api/v1/mpesa/sessions/{shift.pk}/reconcile/", {"actual_cash": "13200", "actual_float": "18500"}, format="json").json()
    assert (D(closed["cash_variance"]), D(closed["float_variance"])) == (0, 0)
    assert (D(closed["business_cash"]), D(closed["business_line"])) == (D("1200.00"), D("500.00"))
    with organization_context(shop.org):
        shift.refresh_from_db()
        assert (shift.closing_cash_actual, shift.closing_float_actual) == (D("12000.00"), D("18000.00"))  # money in operation stays the agency's
    # The next shift opens from the same count with nothing to explain.
    assert open_shift(shop, 13200, 18500).status_code == 201


def test_money_missing_from_the_drawer_is_the_shifts_difference(lintech):
    shop = lintech
    shift = open_shift(shop, 5000, 10000).json()
    sell(shop, 1000)
    short = shop.client.post(f"/api/v1/mpesa/sessions/{shift['id']}/reconcile/", {"actual_cash": "5800", "actual_float": "10000"}, format="json")
    assert short.status_code == 400 and "reason is required" in str(short.json())
    closed = shop.client.post(f"/api/v1/mpesa/sessions/{shift['id']}/reconcile/", {"actual_cash": "5800", "actual_float": "10000",
                              "reason": "200 missing"}, format="json").json()
    assert D(closed["cash_variance"]) == D("-200.00")


def test_a_count_below_the_businesss_own_money_is_refused_with_how_to_fix_it(lintech):
    shop = lintech
    sell(shop, 1000)
    refused = open_shift(shop, 800, 0)
    assert refused.status_code == 400 and "business's own money alone should be cash 1,000.00" in str(refused.json())


def test_sales_paid_to_a_till_of_its_own_are_not_on_the_agent_line(lintech):
    shop = lintech
    assert shop.client.patch("/api/v1/tenancy/settings/", {"sale_mpesa_to": "TILL"}, format="json").json()["sale_mpesa_to"] == "TILL"
    sell(shop, 500, "MPESA", "SKB2222222")
    opened = open_shift(shop, 4000, 9000)
    with organization_context(shop.org):
        shift = MpesaSession.objects.get(pk=opened.json()["id"])
        assert (shift.opening_float, shift.business_line_at_open) == (D("9000.00"), D("0.00"))


def test_separate_drawers_keep_the_agency_shift_to_the_agencys_money(lintech):
    shop = lintech
    shop.client.patch("/api/v1/tenancy/settings/", {"money_mode": "SEPARATE_CASH"}, format="json")
    sell(shop, 1000)
    opened = open_shift(shop, 3000, 5000)
    assert opened.status_code == 201 and opened.json()["business_cash_at_open"] is None
    assert shop.client.get("/api/v1/mpesa/dashboard/").json()["combined"] is None


def test_every_sale_adds_to_money_in_operation_with_one_drawer(lintech):
    shop = lintech
    sell(shop, 1000)
    shift = open_shift(shop, 11000, 20000).json()
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    # All that was counted, the shop's 1,000 included.
    assert (D(str(board["in_operation"]["total"])), D(str(board["in_operation"]["opening"]))) == (D("31000.00"), D("31000.00"))
    sell(shop, 300)
    sell(shop, 200, "MPESA", "SKC3333333")
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert D(str(board["in_operation"]["total"])) == D("31500.00")
    assert (D(str(board["cash"])), D(str(board["float"]))) == (D("10000.00"), D("20000.00"))  # the agency's part, for closing
    outlet = shop.client.get("/api/v1/mpesa/outlets/").json()
    outlet = (outlet["results"] if isinstance(outlet, dict) else outlet)[0]
    assert D(str(outlet["money_in_operation"]["total"])) == D("31500.00")
    home = shop.client.get("/api/v1/inventory/dashboard/").json()
    assert D(str(home["mpesa"]["in_operation"])) == D("31500.00")
    assert D(str(home["mpesa"]["business_cash"])) == D("1300.00")
    # Closed, a later sale still adds to it.
    shop.client.post(f"/api/v1/mpesa/sessions/{shift['id']}/reconcile/", {"actual_cash": "11300", "actual_float": "20200"}, format="json")
    sell(shop, 100)
    assert D(str(shop.client.get("/api/v1/inventory/dashboard/").json()["mpesa"]["in_operation"])) == D("31600.00")


def test_net_worth_shows_the_one_drawer_as_one_figure(lintech):
    shop = lintech
    sell(shop, 1000)
    open_shift(shop, 11000, 20000)
    sell(shop, 300)
    sell(shop, 200, "MPESA", "SKD4444444")
    home = shop.client.get("/api/v1/inventory/dashboard/").json()
    groups = {g["key"]: g for g in home["net_worth"]["groups"]}
    # The same figure as the desk: the agency's 30,000 and the shop's 1,500 together; the drawer and line are not shop money too.
    assert D(str(groups["agency"]["amount"])) == D(str(home["mpesa"]["in_operation"])) == D("31500.00")
    assert not any(item["method"] in ("CASH", "MPESA") for item in groups["money"]["items"])
    item = groups["agency"]["items"][0]
    assert (D(str(item["business_cash"])), D(str(item["business_line"]))) == (D("1300.00"), D("200.00"))


def test_each_part_shows_its_share_of_all_the_money_held(lintech):
    shop = lintech
    sell(shop, 1000)                                  # 1 charger bought at 100
    open_shift(shop, 11000, 20000)
    sell(shop, 500, "MPESA", "SKE5555555")
    shares = shop.client.get("/api/v1/accounting/one-drawer/").json()["shares"]
    parts = {part["key"]: part for part in shares["parts"]}
    assert D(str(shares["total"])) == D(str(shop.client.get("/api/v1/inventory/dashboard/").json()["mpesa"]["in_operation"])) == D("31500.00")
    assert D(str(parts["SHOP"]["amount"])) == D("1500.00") and D(str(parts["MPESA"]["amount"])) == D("30000.00")
    assert (D(str(parts["SHOP"]["sales"])), D(str(parts["SHOP"]["cogs"])), D(str(parts["SHOP"]["profit"]))) == (D("1500.00"), D("200.00"), D("1300.00"))
    assert sum(D(str(part["amount"])) for part in shares["parts"]) == D(str(shares["total"]))


def test_separate_drawers_have_no_shares(lintech):
    shop = lintech
    shop.client.patch("/api/v1/tenancy/settings/", {"money_mode": "SEPARATE_CASH"}, format="json")
    assert shop.client.get("/api/v1/accounting/one-drawer/").json()["shares"] is None


def test_each_sale_shows_all_the_money_held_right_after_it(lintech):
    shop = lintech
    sell(shop, 1000)
    open_shift(shop, 11000, 20000)                     # 30,000 the agency's, 1,000 the shop's
    sell(shop, 300)
    sell(shop, 200, "MPESA", "SKF6666666")
    sales = shop.client.get("/api/v1/commerce/sales/").json()["results"]   # newest first
    assert [D(str(sale["held_after"])) for sale in sales] == [D("31500.00"), D("31300.00"), D("1000.00")]  # the first came before the shift opened
    shop.client.patch("/api/v1/tenancy/settings/", {"money_mode": "SEPARATE_CASH"}, format="json")
    assert "held_after" not in shop.client.get("/api/v1/commerce/sales/").json()["results"][0]


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
    assert books["count"] == 1 and books["months"] and D(str(books["money"]["amount"])) == D("1000.00") and books["money"]["one_drawer"]
    agency = shop.client.get("/api/v1/inventory/parts/MPESA/").json()
    assert D(str(agency["money"]["amount"])) == D("30000.00") and D(str(agency["money"]["of"])) == D("31000.00")
    assert shop.client.get("/api/v1/inventory/parts/NOPE/").status_code == 403
