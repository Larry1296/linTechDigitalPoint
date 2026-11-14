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
        move(investment=fund, user=owner, kind="DEPOSIT", amount="1000", source="OWNER", key="dep")
        record_statement(investment=fund, user=owner, balance="1250", key="stmt")
    summary = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]["all_time"]
    # Not a sale of anything, but the business's profit, on its own line.
    assert (D(str(summary["products"])), D(str(summary["sales"])), D(str(summary["interest"])), D(str(summary["profit"]))) == (D("0"), D("0"), D("250"), D("250"))
    report = client.get("/api/v1/accounting/reports/").json()
    assert (D(str(report["totals"]["revenue"])), D(str(report["totals"]["interest"])), D(str(report["totals"]["net_profit"]))) == (0, D("250"), D("250"))


def test_m_pesa_card_shows_the_last_shift_closed_with_between_shifts():
    owner = User.objects.create_user("between-shifts", password="Safe-pass-1848")
    org = Organization.objects.create(name="Agency shop", slug="between", owner=owner, enabled_modules=["mpesa", "reports"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    with organization_context(org):
        from apps.mpesa.models import MpesaOutlet
        from apps.mpesa.services import open_session, post_transaction, reconcile_session
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Main"), display_name="Agent till")
        session = open_session(outlet=outlet, operator=owner, opening_cash="5000", opening_float="20000", commission_balance="100")
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="1000", user=owner, idempotency_key="d1")
        reconcile_session(session=session, user=owner, actual_cash="6000", actual_float="19000")
    mpesa = client.get("/api/v1/inventory/dashboard/").json()["mpesa"]
    assert mpesa["open_sessions"] == 0 and mpesa["live"] is False and mpesa["as_of"]
    assert (D(str(mpesa["cash"])), D(str(mpesa["float"])), D(str(mpesa["in_operation"]))) == (D("6000"), D("19000"), D("25000"))
    assert D(str(mpesa["commission_balance"])) >= D("100")


def test_what_was_sold_since_the_start_is_goods_services_commission_and_interest_adding_to_the_total():
    """The dashboard's "What the business has brought in" card: the books' amounts by what they were, the counts beside
    them, and a total that is every line added up. A tool the business uses shows even before anything is recorded."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.catalog.models import Category, Product, ProductVariant
    from apps.inventory.services import complete_stock_receipt
    owner = User.objects.create_user("sold-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Sold shop", slug="sold", owner=owner,
                                      enabled_modules=["inventory", "pos", "services", "mpesa", "investments", "reports", "expenses"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    today = timezone.localdate()
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    with organization_context(org):
        from apps.accounting.investments import move, open_investment, record_statement
        from apps.cyber.services import create_service
        from apps.mpesa.models import MpesaOutlet
        from apps.mpesa.services import open_session
        store = Store.objects.create(name="Main")
        category = Category.objects.create(name="Chargers", slug="chargers")
        charger = ProductVariant.objects.create(product=Product.objects.create(name="Charger", slug="charger", category=category),
                                                name="Standard", sku="CHG-S", selling_price=300, minimum_price=250)
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-S", received_at=timezone.now() - timedelta(hours=1),
                               lines=[{"variant_id": charger.pk, "received_quantity": "10", "unit_cost": "160"}], user=owner)
        charging = create_service(owner, "Phone charging", "10")
        outlet = MpesaOutlet.objects.create(store=store, display_name="Agent till")
        open_session(outlet=outlet, operator=owner, opening_cash="5000", opening_float="20000")
        fund = open_investment(user=owner, name="CIC MMF")
        move(investment=fund, user=owner, kind="DEPOSIT", amount="1000", source="OWNER", key="dep")
        record_statement(investment=fund, user=owner, balance="1250", key="stmt")
    assert client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": charger.pk, "quantity": 2}]}, format="json").status_code == 201
    assert client.post(f"/api/v1/cyber/income/{charging.variant.product_id}/", {"option_id": charging.pk, "quantity": "2",
                       "payment_method": "CASH", "idempotency_key": "c1"}, format="json").status_code == 201
    assert client.post("/api/v1/mpesa/commission/", {"outlet": outlet.pk, "period": str(last_month), "amount": "700", "reference": "SOLD01",
                       "settlement_method": "MPESA", "idempotency_key": "SOLD01"}, format="json").status_code == 201
    assert client.post("/api/v1/accounting/money-check/starting/", {"method": "CASH", "amount": "1000", "idempotency_key": "start"}, format="json").status_code == 201
    summary = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]
    sold = summary["sold"]
    groups = {group["key"]: group for group in sold["groups"]}
    assert [group["key"] for group in sold["groups"]] == ["GOODS", "SERVICES", "COMMISSION", "INTEREST"]
    line = lambda key, code: next(row for row in groups[key]["lines"] if row["code"] == code)
    assert (D(line("GOODS", "4000")["amount"]), line("GOODS", "4000")["sales"], D(line("GOODS", "4000")["quantity"])) == (D("600"), 1, D("2"))
    assert (D(line("SERVICES", "4020")["amount"]), D(line("SERVICES", "4020")["quantity"])) == (D("20"), D("2"))
    assert (D(line("COMMISSION", "4010")["amount"]), line("COMMISSION", "4010")["months_paid"]) == (D("700"), 1)
    assert D(groups["INTEREST"]["amount"]) == D("250")
    # The menu, rooms and M-KOPA are not used, so they are not shown; the total is every line added up.
    assert {row["code"] for group in sold["groups"] for row in group["lines"]} == {"4000", "4020", "4010", "4910"}
    assert D(sold["total"]) == D("1570") == sum(D(group["amount"]) for group in sold["groups"])
    # From the total sold and earned to the business's money now: every shilling was received (nothing on credit), the
    # owner started with 1,000 in the drawer, and the interest stays in the fund. It always ends exactly at the money now.
    bridge = summary["money_bridge"]
    assert {line["key"]: D(line["amount"]) for line in bridge["lines"]} == {"starting": D("1000")}
    assert (D(bridge["in_places"]), D(bridge["in_investments"]), D(bridge["money_now"])) == (D("2320"), D("250"), D("2570"))
    assert D(sold["total"]) + sum(D(line["amount"]) for line in bridge["lines"]) == D(bridge["money_now"])


def test_money_the_owner_says_is_already_invested_leaves_the_drawer_and_nothing_else_changes():
    """An owner who keeps all the business's money in an investment: the drawer the app still counts is brought to zero,
    recorded as money already in the investment. The investment, what was sold and the profit stay the same."""
    from django.core.management import call_command
    from io import StringIO
    owner = User.objects.create_user("already-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Already shop", slug="already", owner=owner, enabled_modules=["services", "investments", "reports", "expenses"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    with organization_context(org):
        from apps.accounting.investments import move, open_investment
        from apps.cyber.services import create_service
        Store.objects.create(name="Main")
        charging = create_service(owner, "Phone charging", "100")
        fund = open_investment(user=owner, name="CIC MMF")
        move(investment=fund, user=owner, kind="DEPOSIT", amount="5000", source="OWNER", key="dep")
    client.post("/api/v1/accounting/money-check/starting/", {"method": "CASH", "amount": "1000", "idempotency_key": "start"}, format="json")
    client.post(f"/api/v1/cyber/income/{charging.variant.product_id}/", {"option_id": charging.pk, "quantity": "3", "payment_method": "CASH", "idempotency_key": "c1"}, format="json")
    before = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]
    assert D(before["money_bridge"]["in_places"]) == D("1300")
    # Shown first, recorded only with --apply.
    out = StringIO()
    call_command("record_already_invested", business=org.pk, place="CASH", fund="CIC MMF", stdout=out)
    assert "Nothing recorded" in out.getvalue() and D(client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]["money_bridge"]["in_places"]) == D("1300")
    call_command("record_already_invested", business=org.pk, place="CASH", fund="CIC MMF", apply=True, stdout=StringIO())
    after = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]
    bridge = after["money_bridge"]
    assert (D(bridge["in_places"]), D(bridge["in_investments"]), D(bridge["money_now"])) == (D("0"), D(before["money_bridge"]["in_investments"]), D(before["money_bridge"]["in_investments"]))
    assert (after["sold"]["total"], after["all_time"]["profit"]) == (before["sold"]["total"], before["all_time"]["profit"])
    assert D(after["sold"]["total"]) + sum(D(line["amount"]) for line in bridge["lines"]) == D(bridge["money_now"])
    places = {p["method"]: D(str(p["expected"])) for p in client.get("/api/v1/accounting/money-check/").json()["places"]}
    assert places["CASH"] == 0
    # Running it again finds nothing to move.
    call_command("record_already_invested", business=org.pk, place="CASH", fund="CIC MMF", apply=True, stdout=StringIO())
    assert D(client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]["money_bridge"]["in_places"]) == 0
