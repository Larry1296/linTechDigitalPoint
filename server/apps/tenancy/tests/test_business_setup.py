"""Any small or medium business is set up from how it makes money, what kind it is, and its own tools."""
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product
from apps.core.models import Store
from apps.tenancy import business_profiles as profiles
from apps.tenancy.context import organization_context
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    client = APIClient()
    client.force_login(User.objects.create_user("new-owner", password="Safe-pass-1848"))
    return client


def create(owner, **values):
    return owner.post("/api/v1/tenancy/create/", {"name": "Test business", **values}, format="json")


def test_a_mixed_business_is_created_with_its_own_tools_contacts_and_location(owner):
    response = create(owner, name="Kiandas Agrovet", business_model="MIXED", sector="agrovet_vet", plan="PRO",
        enabled_modules=["services", "inventory", "pos", "customers", "reports"],
        branch_name="Kiandas market stall", phone="0712 000 111", email="hello@agrovet.example",
        address="Kiandas, Kiambu", country="UG", currency="UGX", timezone="Africa/Kampala", opening_cash="15000")
    assert response.status_code == 201, response.content
    data = response.json()
    assert data["name"] == "Kiandas Agrovet" and data["currency"] == "UGX" and data["country"] == "UG"
    assert data["enabled_modules"] == ["customers", "inventory", "pos", "reports", "services"]
    assert (data["business_model"], data["sector"], data["business_type"]) == ("MIXED", "agrovet_vet", "Agrovet with vet services")
    organization = Organization.objects.get(pk=data["id"])
    assert (organization.phone, organization.address) == ("0712 000 111", "Kiandas, Kiambu")
    with organization_context(organization):
        branch = Store.objects.get()
        assert (branch.name, branch.phone, branch.timezone) == ("Kiandas market stall", "0712 000 111", "Africa/Kampala")
    report = owner.get(f"/api/v1/accounting/ledger/reports/?branch={branch.pk}").json()
    assert Decimal(str(report["balance_sheet"]["assets"])) == 15000
    # The starting cash is in the drawer too, not only in the books: Money check and net worth start from it.
    with organization_context(organization):
        from apps.accounting.money_check import expected
        assert expected("CASH")[0] == 15000


@pytest.mark.parametrize("model,modules,message", [
    ("GOODS", [], "Choose at least one tool"),
    ("GOODS", ["pos", "reports"], "Turn on Products & stock"),
    ("GOODS", ["inventory", "services"], "Services & jobs cannot be used when you only sell goods"),
    ("SERVICES", ["services", "locations"], "Shelves & locations cannot be used when you only provide services"),
    ("SERVICES", ["services", "inventory", "pos"], "Products & stock cannot be used when you only provide services"),
    ("SERVICES", ["pos", "reports"], "Turn on Services & jobs or M-Pesa agency"),
    ("MIXED", ["reports"], "Turn on Products & stock or Services & jobs"),
])
def test_tools_that_do_not_fit_the_business_are_explained(owner, model, modules, message):
    response = create(owner, name="Half set up", business_model=model, enabled_modules=modules)
    assert response.status_code == 400 and message in str(response.json())
    assert not Organization.objects.filter(name="Half set up").exists()


def test_older_clients_that_send_only_tools_still_create_a_fitting_business(owner):
    response = create(owner, enabled_modules=["inventory", "pos"])
    assert response.status_code == 201 and response.json()["business_model"] == "GOODS"


def test_the_kind_of_business_must_match_how_it_makes_money(owner):
    response = create(owner, business_model="GOODS", sector="barber", enabled_modules=["inventory", "pos"])
    assert response.status_code == 400 and "does not match" in str(response.json())
    response = create(owner, business_model="SERVICES", sector="other_services", enabled_modules=["services", "pos"])
    assert response.status_code == 400 and "Describe what your business does" in str(response.json())


def test_a_barbershop_sells_its_services_without_any_stock_or_shelves(owner):
    response = create(owner, name="Fresh Cuts", business_model="SERVICES", sector="barber", business_size="SOLO",
        enabled_modules=["services", "pos", "expenses", "reports"],
        starter_services=[{"name": "Haircut", "selling_price": "200"}, {"name": "Shave", "selling_price": "100"}],
        starter_categories=["Should be ignored"])
    assert response.status_code == 201, response.content
    assert response.json()["business_type"] == "Barbershop"
    with organization_context(Organization.objects.get(name="Fresh Cuts")):
        assert set(Product.objects.values_list("name", "product_type")) == {("Haircut", "SERVICE"), ("Shave", "SERVICE")}
        assert not Category.objects.filter(name="Should be ignored").exists()
    catalog = owner.get("/api/v1/commerce/pos/catalog/").json()
    assert sorted(row["product_name"] for row in catalog) == ["Haircut", "Shave"]
    haircut = next(row for row in catalog if row["product_name"] == "Haircut")
    sale = owner.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": haircut["id"], "quantity": 1}]}, format="json")
    assert sale.status_code in (200, 201), sale.content
    assert owner.get("/api/v1/locations/shelves/").status_code == 403
    assert owner.get("/api/v1/inventory/receipts/").status_code == 403


def test_a_mama_mboga_starts_with_her_produce_categories(owner):
    response = create(owner, name="Mama Wanjiru", business_model="GOODS", sector="mama_mboga",
        enabled_modules=["inventory", "pos", "expenses", "reports"], starter_categories=["Vegetables", "Fruits", "Vegetables"],
        starter_services=[{"name": "Not a service business", "selling_price": "10"}])
    assert response.status_code == 201, response.content
    with organization_context(Organization.objects.get(name="Mama Wanjiru")):
        assert sorted(Category.objects.values_list("name", flat=True)) == ["Fruits", "Vegetables"]
        assert not Product.objects.exists()


def test_settings_apply_the_same_rules_when_the_business_grows(owner):
    create(owner, name="Salon", business_model="SERVICES", sector="salon", enabled_modules=["services", "customers"])
    response = owner.patch("/api/v1/tenancy/settings/", {"enabled_modules": ["services", "inventory"]}, format="json")
    assert response.status_code == 400 and "Products & stock cannot be used" in str(response.json())
    # The salon starts selling hair products: it becomes a business that does both.
    response = owner.patch("/api/v1/tenancy/settings/", {"business_model": "MIXED", "sector": "salon_shop",
                                                         "enabled_modules": ["services", "inventory", "pos"]}, format="json")
    assert response.status_code == 200, response.content
    assert (response.json()["business_model"], response.json()["business_type"]) == ("MIXED", "Salon with beauty products")
    # Changing the model alone clears a kind of business that belongs to the old model.
    response = owner.patch("/api/v1/tenancy/settings/", {"business_model": "GOODS", "enabled_modules": ["inventory", "pos"]}, format="json")
    assert response.status_code == 200 and response.json()["sector"] == ""


def test_the_business_catalogue_is_public_and_every_suggestion_is_valid(client):
    data = client.get("/api/v1/tenancy/business-profiles/").json()
    assert [model["id"] for model in data["models"]] == ["GOODS", "SERVICES", "MIXED"]
    for model, sectors in data["sectors"].items():
        assert sectors, model
        for sector in sectors:
            for size, modules in sector["modules"].items():
                assert profiles.module_problems(model, modules) == [], (model, sector["id"], size)
            if model == "SERVICES":
                assert not sector["categories"] and "inventory" not in sector["modules"]["MEDIUM"]
            if model == "GOODS":
                assert not sector["services"] and "services" not in sector["modules"]["MEDIUM"]


def test_the_frontend_test_fixture_matches_the_catalogue():
    """The client tests run against a copy of the catalogue; regenerate it when the catalogue changes (see docs/business-profiles.md)."""
    import json
    from pathlib import Path
    fixture = Path(__file__).resolve().parents[4] / "client/src/modules/platform/businessProfiles.fixture.json"
    if not fixture.exists():
        pytest.skip("client sources are not present")
    assert json.loads(fixture.read_text()) == json.loads(json.dumps(profiles.catalogue()))


REGISTRATION = {"first_name": "Wanjiru", "last_name": "Kamau", "phone": "0712 345-678", "username": "wanjiru",
                "email": "wanjiru@example.test", "password": "Kiandas-pass-2026", "password_confirm": "Kiandas-pass-2026"}


def test_an_owner_registers_with_their_name_phone_and_a_confirmed_password():
    client = APIClient()
    response = client.post("/api/v1/tenancy/register/", REGISTRATION, format="json")
    assert response.status_code == 201, response.content
    assert (response.json()["first_name"], response.json()["last_name"], response.json()["phone"]) == ("Wanjiru", "Kamau", "0712345678")
    user = User.objects.get(username="wanjiru")
    assert (user.get_full_name(), user.account_profile.phone) == ("Wanjiru Kamau", "0712345678")


@pytest.mark.parametrize("changes,message", [
    ({"password_confirm": "Different-pass-2026"}, "The two passwords do not match."),
    ({"phone": "12ab"}, "Enter a phone number"),
    ({"first_name": ""}, "first_name"),
    ({"username": "has space"}, "no spaces"),
])
def test_registration_explains_what_to_fix(changes, message):
    response = APIClient().post("/api/v1/tenancy/register/", {**REGISTRATION, **changes}, format="json")
    assert response.status_code == 400 and message in str(response.json())
    assert not User.objects.filter(username=REGISTRATION["username"]).exists()


def test_an_email_already_in_use_cannot_open_a_second_account():
    User.objects.create_user("someone", email="WANJIRU@example.test", password="x")
    response = APIClient().post("/api/v1/tenancy/register/", REGISTRATION, format="json")
    assert response.status_code == 400 and "Unable to register" in str(response.json())
