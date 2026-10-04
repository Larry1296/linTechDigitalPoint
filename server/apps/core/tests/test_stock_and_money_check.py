"""Stock check and money check: counted figures next to what the app expects, settled honestly."""
from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.services import complete_stock_receipt
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def owner_shop():
    owner = User.objects.create_user("checker", password="Safe-pass-1848")
    org = Organization.objects.create(name="Check shop", slug="check", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
        category = Category.objects.create(name="Chargers", slug="chargers")
        charger = ProductVariant.objects.create(product=Product.objects.create(name="Normal charger", slug="charger", category=category),
                                                name="Standard", sku="CHG-1", selling_price=300, minimum_price=250)
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-1", received_at=timezone.now() - timedelta(hours=1),
                               lines=[{"variant_id": charger.pk, "received_quantity": "10", "unit_cost": "160"}], user=owner)
    client = APIClient()
    client.force_authenticate(owner)
    return client, org, charger


def test_stock_check_lists_products_and_settles_missing_and_found_items(owner_shop):
    client, org, charger = owner_shop
    rows = client.get("/api/v1/inventory/stock-check/").json()
    row = next(r for r in rows if r["id"] == charger.pk)
    assert (D(row["on_shelf"]), D(row["buying_price"]), D(row["selling_price"])) == (D("10"), D("160"), D("300"))
    # Counted 7 of 10: 2 were sold (recorded through the till), 1 was lost.
    sold = client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": charger.pk, "quantity": 2, "unit_price": "280"}]}, format="json")
    assert sold.status_code == 201, sold.content
    lost = client.post("/api/v1/inventory/stock-check/", {"variant_id": charger.pk, "quantity": "1", "kind": "lost"}, format="json")
    assert lost.status_code == 201, lost.content
    assert D(next(r for r in lost.json() if r["id"] == charger.pk)["on_shelf"]) == D("7")
    found = client.post("/api/v1/inventory/stock-check/", {"variant_id": charger.pk, "quantity": "1", "kind": "found"}, format="json")
    assert D(next(r for r in found.json() if r["id"] == charger.pk)["on_shelf"]) == D("8")
    with organization_context(org):
        from apps.accounting import statements
        pl = statements.profit_and_loss(None, None)
    assert pl["revenue"] == D("560.00") and pl["direct_costs"] == D("320.00")
    assert pl["stock_corrections"] == D("160.00")  # the lost charger is a loss; the found one adds nothing to profit
    assert pl["net_profit_before_tax"] == D("80.00")


def test_money_check_expects_starting_money_plus_sales_less_spending(owner_shop):
    client, org, charger = owner_shop
    assert client.post("/api/v1/accounting/money-check/starting/", {"method": "CASH", "amount": "5000", "note": "Drawer on day one",
                       "idempotency_key": "start-1"}, format="json").status_code == 201
    client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": charger.pk, "quantity": 1}]}, format="json")  # +300 cash
    with organization_context(org):
        from apps.accounting.models import ExpenseCategory
        from apps.accounting.services import record_expense
        rent = ExpenseCategory.objects.create(name="Transport")
        record_expense(user=None, category=rent, unit="SHOP", method="CASH", amount="200", description="Boda to town", key="exp-1")
    data = client.get("/api/v1/accounting/money-check/").json()
    cash = next(p for p in data["places"] if p["method"] == "CASH")
    parts = {p["key"]: D(p["amount"]) for p in cash["parts"]}
    assert D(cash["expected"]) == D("5100.00") and parts["starting"] == D("5000") and parts["received"] == D("300") and parts["expenses"] == D("-200")
    counted = client.post("/api/v1/accounting/money-check/", {"method": "CASH", "cash_count": {"1000": 5, "50": 1, "coins": "20"},
                          "note": "Evening count"}, format="json")
    assert counted.status_code == 201, counted.content
    assert (D(counted.json()["actual"]), D(counted.json()["difference"])) == (D("5070.00"), D("-30.00"))
    history = client.get("/api/v1/accounting/money-check/").json()["history"]
    assert history[0]["note"] == "Evening count" and history[0]["cash_count"]["1000"] == 5


def test_money_check_is_shop_money_only_never_the_mpesa_agency(owner_shop):
    client, org, charger = owner_shop
    with organization_context(org):
        from apps.mpesa.models import MpesaOutlet
        from apps.mpesa.services import open_session, record_commission
        from django.contrib.auth.models import User
        owner = User.objects.get(username="checker")
        outlet = MpesaOutlet.objects.create(store=Store.objects.get(), display_name="Agent till")
        open_session(outlet=outlet, operator=owner, opening_cash="20000", opening_float="30000")
        record_commission(outlet=outlet, user=owner, period=timezone.localdate(), commission_amount="400", reference="COMM", settlement_method="CASH")
        record_commission(outlet=outlet, user=owner, period=timezone.localdate(), commission_amount="300", reference="COMM-2", settlement_method="MPESA")
    data = client.get("/api/v1/accounting/money-check/").json()
    assert [p["method"] for p in data["places"]] == ["CASH", "MPESA"]  # the drawer and the Lipa na M-Pesa till
    assert all(D(p["expected"]) == 0 for p in data["places"])  # agency cash and commission are not shop money
    client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": charger.pk, "quantity": 1}], "payment_method": "MPESA",
                "payment_reference": "SJK4ABC123"}, format="json")
    till = next(p for p in client.get("/api/v1/accounting/money-check/").json()["places"] if p["method"] == "MPESA")
    assert D(till["expected"]) == 0  # an M-Pesa sale counts in the till once its code is confirmed, not before


def test_mpesa_sale_at_the_lowest_price_waits_then_is_confirmed_from_the_till(owner_shop):
    client, org, charger = owner_shop
    sold = client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": charger.pk, "quantity": 1, "unit_price": "250"}],
                       "payment_method": "MPESA", "payment_reference": "SJK4H7XQ2P"}, format="json")
    assert sold.status_code == 201, sold.content
    waiting = sold.json()["waiting_payment"]
    assert (waiting["method"], D(waiting["amount"]), waiting["reference"]) == ("MPESA", D("250"), "SJK4H7XQ2P")
    confirmed = client.post(f"/api/v1/commerce/payments/{waiting['id']}/confirm/", {"reference": "SJK4H7XQ2P"}, format="json")
    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["status"] == "COMPLETED"
    with organization_context(org):
        from apps.commerce.models import Sale
        from apps.commerce.returns import sale_balance
        assert sale_balance(Sale.objects.get(pk=sold.json()["sale_id"])) == D("0")


def test_cash_sale_has_nothing_waiting(owner_shop):
    client, _, charger = owner_shop
    sold = client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": charger.pk, "quantity": 1}]}, format="json")
    assert sold.status_code == 201 and "waiting_payment" not in sold.json()


def _paid_twice(client, charger):
    """M-Pesa 250 left waiting, then the same 250 recorded again as cash from the Sales page."""
    sold = client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": charger.pk, "quantity": 1, "unit_price": "250"}],
                       "payment_method": "MPESA"}, format="json").json()
    cash = client.post(f"/api/v1/commerce/sales/{sold['sale_id']}/payments/", {"amount": "250", "method": "CASH", "idempotency_key": "cash-1"}, format="json")
    assert cash.status_code == 201, cash.content
    return sold["sale_id"], sold["waiting_payment"]["id"], cash.json()["id"]


def test_confirming_mpesa_on_a_sale_already_paid_in_cash_explains_what_to_do(owner_shop):
    client, _, charger = owner_shop
    _, mpesa, _ = _paid_twice(client, charger)
    refused = client.post(f"/api/v1/commerce/payments/{mpesa}/confirm/", {"reference": "UISGC86FCY"}, format="json")
    assert refused.status_code == 400
    text = str(refused.json())
    assert "cash 250.00" in text and "reverse the other payment first" in text


def test_reversing_the_wrong_cash_then_confirming_mpesa_leaves_one_payment(owner_shop):
    client, org, charger = owner_shop
    sale_id, mpesa, cash = _paid_twice(client, charger)
    assert client.post(f"/api/v1/commerce/payments/{cash}/reverse/", {"reason": "Customer paid by M-Pesa, not cash"}, format="json").status_code == 200
    confirmed = client.post(f"/api/v1/commerce/payments/{mpesa}/confirm/", {"reference": "UISGC86FCY"}, format="json")
    assert confirmed.status_code == 200, confirmed.content
    with organization_context(org):
        from apps.commerce.models import Sale
        from apps.commerce.returns import sale_amounts
        assert sale_amounts(Sale.objects.get(pk=sale_id)) == (D("250.00"), D("250.00"))


def test_a_waiting_mpesa_that_duplicates_cash_can_be_marked_not_received(owner_shop):
    client, org, charger = owner_shop
    sale_id, mpesa, _ = _paid_twice(client, charger)
    assert client.post(f"/api/v1/commerce/payments/{mpesa}/not-received/", {}, format="json").status_code == 400
    dropped = client.post(f"/api/v1/commerce/payments/{mpesa}/not-received/", {"reason": "Customer paid cash instead"}, format="json")
    assert dropped.status_code == 200 and dropped.json()["status"] == "FAILED"
    with organization_context(org):
        from apps.commerce.models import Sale
        from apps.commerce.returns import sale_amounts
        assert sale_amounts(Sale.objects.get(pk=sale_id)) == (D("250.00"), D("250.00"))
