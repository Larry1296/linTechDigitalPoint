"""Sales history: finding a sale, listing only what is owed, and naming who owes a Walk-in balance."""
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.accounting import statements
from apps.accounting.models import CashEntry
from apps.accounting.services import reverse
from apps.catalog.models import Category, Product, ProductVariant
from apps.commerce.receipts import receipt_data
from apps.commerce.returns import adjust_sale_price
from apps.core.models import AuditLog, Store
from apps.inventory.services import complete_sale, complete_stock_receipt
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def shop():
    owner = User.objects.create_user("seller", password="Safe-pass-1848")
    org = Organization.objects.create(name="Glue shop", slug="glue", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
        category = Category.objects.create(name="Hardware", slug="hardware")
        glue = ProductVariant.objects.create(product=Product.objects.create(name="Super glue", slug="glue", category=category),
                                             name="3g", sku="GLU-1", selling_price=50)
        bulb = ProductVariant.objects.create(product=Product.objects.create(name="Rechargeable bulb", slug="bulb", category=category),
                                             name="50W", sku="BLB-1", selling_price=600)
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-1", user=owner, lines=[
            {"variant_id": glue.pk, "received_quantity": "10", "unit_cost": "20"},
            {"variant_id": bulb.pk, "received_quantity": "5", "unit_cost": "350"}])
    client = APIClient()
    client.force_login(owner)
    return {"org": org, "owner": owner, "glue": glue, "bulb": bulb, "client": client}


def sell(shop, variant, number, **extra):
    with organization_context(shop["org"]):
        return complete_sale(lines=[{"variant": variant, "quantity": 1}], channel="POS", number=number, user=shop["owner"], **extra)


def test_search_and_owing_filter_find_the_sale_that_still_owes(shop):
    glue = sell(shop, shop["glue"], "POS-GLUE")
    sell(shop, shop["bulb"], "POS-BULB")
    client = shop["client"]
    found = client.get("/api/v1/commerce/sales/", {"q": "glue"}).json()
    assert [row["number"] for row in found["results"]] == ["POS-GLUE"] and found["count"] == 1
    assert client.get("/api/v1/commerce/sales/", {"owing": "1"}).json()["count"] == 0
    # Given on credit but rung up as paid: reversing the payment makes it owed again.
    with organization_context(shop["org"]):
        reverse(entry=CashEntry.objects.get(source_key=f"payment:{glue.payments.get().pk}"), user=shop["owner"], reason="Given on credit")
    owing = client.get("/api/v1/commerce/sales/", {"owing": "1"}).json()
    assert [(row["number"], D(row["outstanding"]), row["customer_id"]) for row in owing["results"]] == [("POS-GLUE", D("50.00"), None)]


def test_a_walk_in_debt_can_be_given_its_customer_once_without_changing_the_books(shop):
    glue = sell(shop, shop["glue"], "POS-GLUE", paid_amount=0)
    client = shop["client"]
    customer = client.post("/api/v1/commerce/customers/", {"name": "John Otieno", "phone": "0712345678"}, format="json").json()
    with organization_context(shop["org"]):
        before = statements.balances()
    named = client.post(f"/api/v1/commerce/sales/{glue.pk}/customer/", {"customer_id": customer["id"]}, format="json")
    assert named.status_code == 200 and named.json()["customer"] == "John Otieno"
    with organization_context(shop["org"]):
        assert statements.balances() == before
        assert [r["customer"] for r in statements.receivables()] == ["John Otieno"]
        assert AuditLog.objects.filter(action="SALE_CUSTOMER_SET", object_id=str(glue.pk)).exists()
    assert client.get("/api/v1/commerce/sales/", {"q": "0712"}).json()["results"][0]["number"] == "POS-GLUE"
    again = client.post(f"/api/v1/commerce/sales/{glue.pk}/customer/", {"customer_id": customer["id"]}, format="json")
    assert again.status_code == 400


def test_a_customer_from_another_business_cannot_be_attached(shop):
    glue = sell(shop, shop["glue"], "POS-GLUE", paid_amount=0)
    other_owner = User.objects.create_user("other", password="Safe-pass-1848")
    other = Organization.objects.create(name="Other", slug="other", owner=other_owner)
    Membership.objects.create(user=other_owner, organization=other, role="OWNER")
    OrganizationSubscription.objects.create(organization=other, status="ACTIVE")
    outsider = APIClient()
    outsider.force_login(other_owner)
    stranger = outsider.post("/api/v1/commerce/customers/", {"name": "Stranger"}, format="json").json()
    response = shop["client"].post(f"/api/v1/commerce/sales/{glue.pk}/customer/", {"customer_id": stranger["id"]}, format="json")
    assert response.status_code == 400


def test_receipt_balance_matches_sales_history_after_a_price_correction(shop):
    bulb = sell(shop, shop["bulb"], "POS-BULB", paid_amount=D("300"))
    with organization_context(shop["org"]):
        adjust_sale_price(sale=bulb, kind="CREDIT", amount=D("100"), reason="Agreed discount later", user=shop["owner"])
        receipt = receipt_data(bulb, shop["org"])
    assert (receipt["total"], receipt["charged"], receipt["paid"], receipt["balance"]) == (D("600.00"), D("500.00"), D("300.00"), D("200.00"))
    listed = shop["client"].get("/api/v1/commerce/sales/").json()["results"][0]
    assert D(listed["outstanding"]) == receipt["balance"]
