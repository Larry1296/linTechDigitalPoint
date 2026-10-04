"""Income per Cyber service: pick a service and price option, record the amount received; options are configurable."""
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def cyber():
    owner = User.objects.create_user("cyber-owner", password="Safe-pass-1848")
    cashier = User.objects.create_user("cyber-till", password="Safe-pass-1848")
    org = Organization.objects.create(name="Cyber shop", slug="cyber-income", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    Membership.objects.create(user=cashier, organization=org, role="CASHIER", permissions=[
        "cyber.view_cyberjob", "cyber.add_cyberjob", "cyber.complete_cyber_job"])
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        from apps.cyber.services import create_service
        Store.objects.create(name="Main")
        printing = create_service(owner, "Printing", "10", billing_unit="PER_PAGE")
        typing = create_service(owner, "Typing", "50", billing_unit="PER_PAGE")
    owner_client, till = APIClient(), APIClient()
    owner_client.force_login(owner)
    till.force_login(cashier)
    return owner_client, till, org, printing, typing


def _record(client, service, option, quantity, key, **extra):
    return client.post(f"/api/v1/cyber/income/{service}/", {"option_id": option, "quantity": quantity, "payment_method": "CASH",
                       "idempotency_key": key, **extra}, format="json")


def _option(client, service, **values):
    body = {"name": "Option", "price": "10", "billing_unit": "PER_PAGE", **values}
    return client.post(f"/api/v1/cyber/income/{service}/options/", body, format="json")


def test_price_options_and_income_per_service_reach_sales_and_the_books(cyber):
    owner, _, org, printing, typing = cyber
    service = printing.variant.product_id
    standard = printing.pk
    assert owner.post(f"/api/v1/cyber/income/options/{standard}/", {"name": "Single side", "price": "10", "minimum_price": "8",
                      "billing_unit": "PER_PAGE", "cost": "3"}, format="json").status_code == 200
    both = _option(owner, service, name="Both sides", price="15")
    assert both.status_code == 201, both.content
    assert [o["name"] for o in both.json()["options"]] == ["Single side", "Both sides"]
    assert _option(owner, service, name="both sides").status_code == 400  # names are unique per service
    both_id = both.json()["options"][1]["id"]
    first = _record(owner, service, standard, "40", "p1")
    assert first.status_code == 201, first.content
    assert _record(owner, service, standard, "40", "p1").json()["today"]["times"] == 1  # double click
    _record(owner, service, both_id, "10", "p2", payment_method="MPESA", payment_reference="sjk4abc123", customer_name="Thesis")
    _record(owner, typing.variant.product_id, typing.pk, "3", "t1")
    detail = owner.get(f"/api/v1/cyber/income/{service}/").json()
    assert D(detail["today"]["amount"]) == D("550")
    assert {o["name"]: D(o["month"]["amount"]) for o in detail["options"]} == {"Single side": D("400"), "Both sides": D("150")}
    assert detail["history"][0]["option"] == "Both sides" and detail["history"][0]["payment_method"] == "MPESA"
    summary = owner.get("/api/v1/cyber/income/").json()
    assert D(summary["totals"]["today"]) == D("700") and len(summary["services"]) == 2
    with organization_context(org):
        from apps.accounting import statements
        services = next(u for u in statements.profit_and_loss(None, None)["units"] if u["key"] == "services")
    assert services["revenue"] == D("700") and services["direct_costs"] == D("120")  # 40 single-sided pages at 3 each


def test_amount_rules_fixed_bargain_and_varies(cyber):
    owner, till, _, printing, _ = cyber
    service = printing.variant.product_id
    # Fixed price: staff take the list price only; managers may change it.
    refused = _record(till, service, printing.pk, "10", "c1", amount="90")
    assert refused.status_code == 400 and "fixed at 100.00" in str(refused.json())
    assert _record(owner, service, printing.pk, "10", "o1", amount="90").status_code == 201
    # Bargaining down to the lowest price.
    owner.post(f"/api/v1/cyber/income/options/{printing.pk}/", {"name": "Standard", "price": "10", "minimum_price": "8", "billing_unit": "PER_PAGE"}, format="json")
    assert _record(till, service, printing.pk, "10", "c2", amount="85").status_code == 201
    low = _record(till, service, printing.pk, "10", "c3", amount="70")
    assert low.status_code == 400 and "lowest for this is 80.00 (8.00 per page)" in str(low.json())
    assert "Charging more needs a manager" in str(_record(till, service, printing.pk, "10", "c4", amount="120").json())
    # An amount that varies: staff type what was received, and must type it.
    other = _option(owner, service, name="Special job", price="0", billing_unit="FIXED", price_varies=True).json()["options"][-1]["id"]
    assert "Enter the amount charged" in str(_record(till, service, other, "1", "c5").json())
    assert _record(till, service, other, "1", "c6", amount="350").status_code == 201
    # An amount that does not divide evenly keeps the exact total and the real number of pages.
    uneven = _record(owner, service, printing.pk, "3", "o2", amount="25")
    row = uneven.json()["history"][0]
    assert (D(row["amount"]), D(row["quantity"])) == (D("25"), D("3"))
    # Staff cannot change options; a service keeps at least one option in use.
    assert _option(till, service, name="Sneaky", price="1").status_code == 403
    alone = owner.post(f"/api/v1/cyber/income/options/{other}/", {"name": "Special job", "price": "0", "billing_unit": "FIXED", "price_varies": True,
                       "active": False}, format="json")
    assert alone.status_code == 200
    detail = owner.get(f"/api/v1/cyber/income/{service}/").json()
    assert [o["active"] for o in detail["options"]] == [True, False]
    assert _record(till, service, other, "1", "c7", amount="10").status_code == 400  # hidden option


def test_new_service_from_the_income_page_and_returned_sales_drop_out(cyber):
    owner, till, org, printing, _ = cyber
    made = owner.post("/api/v1/cyber/income/", {"name": "Binding", "option_name": "Spiral", "price": "150", "billing_unit": "PER_DOCUMENT"}, format="json")
    assert made.status_code == 201 and made.json()["options"][0]["name"] == "Spiral"
    assert owner.post("/api/v1/cyber/income/", {"name": "binding", "price": "1"}, format="json").status_code == 400
    assert till.post("/api/v1/cyber/income/", {"name": "Other", "price": "1"}, format="json").status_code == 403
    sold = _record(owner, printing.variant.product_id, printing.pk, "2", "p1").json()
    with organization_context(org):
        from apps.commerce.models import Sale
        Sale.objects.filter(pk=sold["history"][0]["sale_id"]).update(status="REFUNDED")
    assert D(owner.get(f"/api/v1/cyber/income/{printing.variant.product_id}/").json()["today"]["amount"]) == D("0")


def test_price_list_groups_kinds_of_a_service_as_options_and_regroups_an_earlier_import(cyber, tmp_path):
    from django.core.management import call_command
    owner, till, org, _, _ = cyber
    with organization_context(org):
        from apps.cyber.services import create_service
        # What an earlier run left: the photocopy kinds as two separate services, nothing recorded on them yet.
        bw = create_service(None, "B&W Photocopy - A4", "0", billing_unit="PER_PAGE")
        colour = create_service(None, "Colour Photocopy - A4", "0", billing_unit="PER_PAGE")
    prices = tmp_path / "prices.csv"
    prices.write_text("name,price\nPrinting - Colour A4,20\nLamination - A4,60\nCover Letter,100\n")
    call_command("add_cyber_price_list", business=org.slug, prices=str(prices))
    call_command("add_cyber_price_list", business=org.slug)  # running again adds nothing
    services = {row["name"]: row for row in owner.get("/api/v1/cyber/income/").json()["services"]}
    assert len(services) == 30 and not any("photo print" in name.lower() for name in services)
    options = lambda name: {o["name"]: D(o["price"]) for o in services[name]["options"]}
    # The shop's own "Printing" keeps its Standard option and gains the kinds from the list.
    assert options("Printing") == {"Standard": D("10"), "B&W A4": D("0"), "Colour A4": D("20")}
    assert options("Lamination") == {"ID card": D("0"), "A5": D("0"), "A4": D("60")}
    assert options("Typing") == {"Standard": D("50"), "Simple page": D("0"), "With formatting": D("0")}
    assert D(services["Cover Letter"]["options"][0]["price"]) == D("100")
    # The two separate photocopy services became one Photocopy service, keeping their options.
    assert {o["id"]: o["name"] for o in services["Photocopy"]["options"]} == {bw.pk: "B&W A4", colour.pk: "Colour A4"}
    assert "B&W Photocopy - A4" not in services and "Colour Photocopy - A4" not in services
    # Grouped as on the sheets; online applications in three sub-groups.
    where = lambda name: (services[name]["group"]["name"], (services[name]["subgroup"] or {}).get("name"))
    assert where("Printing") == ("Printing & Copying", None) and where("Photocopy") == ("Printing & Copying", None)
    assert where("Typing") == ("Document Services", None) and where("Lamination") == ("Finishing & Files", None)
    assert where("KUCCPS application assistance") == ("Online Applications", "NTSA & Education")
    listing = owner.get("/api/v1/cyber/income/").json()["groups"]
    assert [g["name"] for g in listing] == ["Printing & Copying", "Document Services", "Finishing & Files", "Online Applications"]
    assert [s["name"] for s in listing[3]["subgroups"]] == ["Government & KRA", "NTSA & Education", "Jobs & Online Services"]
    kuccps = services["KUCCPS application assistance"]
    blocked = _record(owner, kuccps["id"], kuccps["options"][0]["id"], "1", "k0")
    assert blocked.status_code == 400 and "Enter the amount charged" in str(blocked.json())
    assert _record(till, kuccps["id"], kuccps["options"][0]["id"], "1", "k1", amount="200").status_code == 201


def test_owner_adds_groups_and_moves_or_renames_a_service(cyber):
    owner, till, _, printing, _ = cyber
    made = owner.post("/api/v1/cyber/income/groups/", {"name": "Design & Branding"}, format="json")
    assert made.status_code == 201, made.content
    design = made.json()["groups"][0]
    sub = owner.post("/api/v1/cyber/income/groups/", {"name": "Business cards", "parent_id": design["id"]}, format="json").json()["groups"][0]["subgroups"][0]
    assert owner.post("/api/v1/cyber/income/groups/", {"name": "design & branding"}, format="json").status_code == 400
    assert till.post("/api/v1/cyber/income/groups/", {"name": "X"}, format="json").status_code == 403
    service = printing.variant.product_id
    moved = owner.post(f"/api/v1/cyber/income/{service}/settings/", {"name": "Printing (all sizes)", "category_id": sub["id"], "notes": "A3 too"}, format="json")
    assert moved.status_code == 200, moved.content
    body = moved.json()
    assert (body["name"], body["group"]["name"], body["subgroup"]["name"], body["notes"]) == ("Printing (all sizes)", "Design & Branding", "Business cards", "A3 too")
    assert owner.post(f"/api/v1/cyber/income/{service}/settings/", {"name": "Typing"}, format="json").status_code == 400  # name taken
    with organization_context(_org(owner)):
        from apps.catalog.models import Category
        stranger = Category.objects.create(name="Phones", slug="phones")
    assert owner.post(f"/api/v1/cyber/income/{service}/settings/", {"name": "Printing", "category_id": stranger.pk}, format="json").status_code == 400
    new = owner.post("/api/v1/cyber/income/", {"name": "Business card design", "category_id": design["id"], "price": "500"}, format="json")
    assert new.status_code == 201 and new.json()["group"]["name"] == "Design & Branding"


def _org(client):
    from apps.tenancy.models import Organization
    return Organization.objects.get(slug="cyber-income")


def test_one_customer_several_services_is_one_receipt_and_one_payment(cyber):
    """Colour printing with design for 30, and three A4 laminations at 50 each: 180 on one receipt."""
    owner, till, org, printing, _ = cyber
    with organization_context(org):
        from apps.cyber.services import create_service
        lamination = create_service(None, "Lamination", "50", billing_unit="PER_ITEM")
    colour = _option(owner, printing.variant.product_id, name="Colour with design", price="0", billing_unit="FIXED", price_varies=True).json()["options"][-1]["id"]
    visit = {"lines": [{"option_id": colour, "quantity": "1", "amount": "30"}, {"option_id": lamination.pk, "quantity": "3"}],
             "payment_method": "MPESA", "payment_reference": "sjk4abc123", "customer_name": "Mary", "idempotency_key": "v1"}
    made = till.post("/api/v1/cyber/income/record/", visit, format="json")
    assert made.status_code == 201, made.content
    assert D(made.json()["total"]) == D("180")
    assert till.post("/api/v1/cyber/income/record/", visit, format="json").json()["sale_id"] == made.json()["sale_id"]  # double click
    with organization_context(org):
        from apps.commerce.models import Sale
        sale = Sale.objects.get(pk=made.json()["sale_id"])
        assert sale.items.count() == 2 and sale.payments.get().amount == D("180") and sale.payments.get().reference == "SJK4ABC123"
    summary = {row["name"]: row for row in owner.get("/api/v1/cyber/income/").json()["services"]}
    assert D(summary["Printing"]["today"]["amount"]) == D("30") and D(summary["Lamination"]["today"]["amount"]) == D("150")
    # A line that breaks its option's rule stops the whole visit, naming the service.
    bad = till.post("/api/v1/cyber/income/record/", {**visit, "idempotency_key": "v2", "lines": [{"option_id": lamination.pk, "quantity": "3", "amount": "100"}]}, format="json")
    assert bad.status_code == 400 and "Lamination: The price for this is fixed at 150.00" in str(bad.json())
    assert till.post("/api/v1/cyber/income/record/", {**visit, "idempotency_key": "v3", "lines": []}, format="json").status_code == 400
