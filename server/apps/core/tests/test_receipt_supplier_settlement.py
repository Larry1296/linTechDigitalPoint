"""A receipt saved as "owe the supplier" is settled from the opened receipt: paid (on the day, from where the money
really came from) or marked as stock already owned. The stock never moves; the books stay balanced; each is undone."""
from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APIClient
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def shop():
    owner = User.objects.create_user("duka-owner", password="Safe-pass-1848")
    cashier = User.objects.create_user("duka-till", password="Safe-pass-1848")
    org = Organization.objects.create(name="Duka", slug="duka", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    Membership.objects.create(user=cashier, organization=org, role="CASHIER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    from apps.catalog.models import Category, Product, ProductVariant
    from apps.inventory.services import complete_stock_receipt
    with organization_context(org):
        Store.objects.create(name="Main")
        category = Category.objects.create(name="Accessories", slug="accessories")
        cover = ProductVariant.objects.create(product=Product.objects.create(name="Phone cover", slug="cover", category=category),
                                              name="Soft", sku="CV-1", selling_price=200)
        receipt = complete_stock_receipt(supplier_name="LYCOM MOBILE ACCESSORIES", external_reference="INV-14", user=owner,
                                         received_at=timezone.now() - timedelta(days=2),
                                         lines=[{"variant_id": cover.pk, "received_quantity": "8", "unit_cost": "95"}])
    client = APIClient()
    client.force_login(owner)
    return {"client": client, "org": org, "owner": owner, "cashier": cashier, "receipt": receipt}


def _url(shop, tail=""):
    return f"/api/v1/inventory/receipts/{shop['receipt'].pk}/{tail}"


def _books(shop):
    with organization_context(shop["org"]):
        from apps.accounting import statements
        from apps.accounting.models import CashEntry, JournalEntry
        for entry in JournalEntry.objects.all():
            lines = entry.lines.aggregate(d=Sum("debit"), c=Sum("credit"))
            assert lines["d"] == lines["c"], entry.description
        accounts = statements.balances()
        cash = {m: CashEntry.objects.filter(account__payment_method=m).aggregate(v=Sum("amount"))["v"] or D(0) for m in ("CASH", "OTHER")}
        return ({code: accounts.get(code, {}).get("balance", D(0)) for code in ("1000", "1030", "1200", "2000", "3000")},
                cash, statements.payables()["suppliers"])


def test_an_unpaid_receipt_shows_what_is_owed(shop):
    supplier = shop["client"].get(_url(shop)).json()["supplier"]
    assert supplier["supplier"] == "LYCOM MOBILE ACCESSORIES"
    assert (D(supplier["amount"]), D(supplier["owed"]), supplier["already_owned"], supplier["can_mark_already_owned"]) == (D("760"), D("760"), False, True)


def test_paid_from_the_drawer_on_the_day_it_was_paid_and_undone(shop):
    client = shop["client"]
    day = (timezone.localdate() - timedelta(days=2)).isoformat()
    paid = client.post(_url(shop, "pay-supplier/"), {"amount": "760", "source": "CASH", "paid_on": day, "idempotency_key": "p1"}, format="json")
    assert paid.status_code == 201, paid.content
    supplier = paid.json()["supplier"]
    assert D(supplier["owed"]) == 0 and supplier["payments"][0]["paid_on"] == day and supplier["payments"][0]["source"] == "CASH"
    assert client.post(_url(shop, "pay-supplier/"), {"amount": "760", "source": "CASH", "paid_on": day, "idempotency_key": "p1"}, format="json").status_code == 201
    accounts, cash, owing = _books(shop)
    assert (accounts["2000"], accounts["1000"], cash["CASH"], owing) == (0, -D("760"), -D("760"), [])  # the retry paid nothing twice
    undo = client.post(_url(shop, f"payments/{supplier['payments'][0]['id']}/undo/"), {"reason": "Entered twice"}, format="json")
    assert undo.status_code == 201, undo.content
    assert D(undo.json()["supplier"]["owed"]) == D("760") and undo.json()["supplier"]["payments"][0]["undone"]
    accounts, cash, _ = _books(shop)
    assert (accounts["2000"], cash["CASH"]) == (-D("760"), 0)


def test_paid_from_the_owners_own_pocket_leaves_the_drawer_alone(shop):
    client = shop["client"]
    paid = client.post(_url(shop, "pay-supplier/"), {"amount": "760", "source": "OWNER", "idempotency_key": "own"}, format="json")
    assert paid.status_code == 201, paid.content
    assert D(paid.json()["supplier"]["owed"]) == 0 and paid.json()["supplier"]["payments"][0]["source"] == "OWNER"
    accounts, cash, owing = _books(shop)
    # Owner money in and straight out to the supplier: the drawer is unchanged and the owner's stake grew by 760.
    assert (accounts["2000"], accounts["1000"], accounts["1030"], cash["CASH"], cash["OTHER"], accounts["3000"], owing) == (0, 0, 0, 0, 0, -D("760"), [])
    entry = paid.json()["supplier"]["payments"][0]["id"]
    assert client.post(_url(shop, f"payments/{entry}/undo/"), {"reason": "Wrong"}, format="json").status_code == 201
    accounts, cash, _ = _books(shop)
    assert (accounts["2000"], accounts["3000"], cash["OTHER"]) == (-D("760"), 0, 0)


def test_stock_already_owned_becomes_opening_stock_without_touching_the_stock(shop):
    client = shop["client"]
    marked = client.post(_url(shop, "already-owned/"), {"reason": "Bought before I started using the app"}, format="json")
    assert marked.status_code == 201, marked.content
    data = marked.json()
    assert data["document_status"] == "OPENING_BALANCE" and D(data["supplier"]["owed"]) == 0 and data["supplier"]["already_owned"]
    assert [D(line["quantity"]) for line in data["lines"]] == [D("8")]  # the stock itself is untouched
    accounts, _, owing = _books(shop)
    assert (accounts["1200"], accounts["2000"], accounts["3000"], owing) == (D("760"), 0, -D("760"), [])
    with organization_context(shop["org"]):
        from apps.assistant.business_tools import purchases_and_suppliers
        assert purchases_and_suppliers(None, {})["total_bought"] in (0, "0", "0.00", D(0))
    assert client.post(_url(shop, "pay-supplier/"), {"amount": "10", "source": "CASH", "idempotency_key": "x"}, format="json").status_code == 400
    back = client.post(_url(shop, "already-owned/undo/"), {"reason": "It was bought from Lycom"}, format="json")
    assert back.status_code == 201, back.content
    assert back.json()["document_status"] == "SUPPLIER_DOCUMENT" and D(back.json()["supplier"]["owed"]) == D("760")
    accounts, _, _ = _books(shop)
    assert (accounts["2000"], accounts["3000"]) == (-D("760"), 0)


def test_a_price_correction_after_marking_already_owned_goes_to_opening_equity(shop):
    client = shop["client"]
    client.post(_url(shop, "already-owned/"), {"reason": "Old stock"}, format="json")
    line = client.get(_url(shop)).json()["lines"][0]
    fixed = client.post(_url(shop, f"lines/{line['id']}/correct/"), {"variant_id": line["variant_id"], "unit_cost": "90", "received_quantity": "8",
                        "reason": "Real buying price", "confirmed": True, "expected_updated_at": line["updated_at"]}, format="json")
    assert fixed.status_code == 200, fixed.content
    accounts, _, owing = _books(shop)
    assert (accounts["1200"], accounts["2000"], accounts["3000"], owing) == (D("720"), 0, -D("720"), [])
    assert client.post(_url(shop, "already-owned/undo/"), {"reason": "Bought after all"}, format="json").status_code == 201
    accounts, _, _ = _books(shop)
    assert (accounts["2000"], accounts["3000"]) == (-D("720"), 0)


def test_wrong_corrections_are_refused_with_a_reason(shop):
    client = shop["client"]
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    before = (timezone.localdate() - timedelta(days=5)).isoformat()
    for body in ({"amount": "800", "source": "CASH"}, {"amount": "100", "source": "CASH", "paid_on": tomorrow},
                 {"amount": "100", "source": "CASH", "paid_on": before}, {"amount": "100", "source": "CARD"}):
        assert client.post(_url(shop, "pay-supplier/"), {**body, "idempotency_key": str(body)}, format="json").status_code == 400
    assert client.post(_url(shop, "already-owned/"), {"reason": ""}, format="json").status_code == 400
    client.post(_url(shop, "pay-supplier/"), {"amount": "100", "source": "MPESA", "idempotency_key": "part"}, format="json")
    refused = client.post(_url(shop, "already-owned/"), {"reason": "Old stock"}, format="json")
    assert refused.status_code == 400 and "payment" in str(refused.content)
    till = APIClient()
    till.force_login(shop["cashier"])
    assert till.post(_url(shop, "pay-supplier/"), {"amount": "100", "source": "CASH", "idempotency_key": "t"}, format="json").status_code == 403
    assert till.post(_url(shop, "already-owned/"), {"reason": "Old"}, format="json").status_code == 403


def test_the_receipts_list_shows_which_receipts_still_owe(shop):
    client = shop["client"]
    assert [D(r["owed"]) for r in client.get("/api/v1/inventory/receipts/").json()] == [D("760")]
    client.post(_url(shop, "already-owned/"), {"reason": "Old stock"}, format="json")
    assert [D(r["owed"]) for r in client.get("/api/v1/inventory/receipts/").json()] == [0]
