"""Owner-managed staff, business settings and self-service setup of services and M-Pesa outlets."""
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership
from apps.catalog.models import Product
from apps.cyber.models import CyberServiceProfile
from apps.inventory.models import Shelf
from apps.mpesa.models import MpesaOutlet
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db
PASSWORD = "Staff-pass-2026-x"


def add_staff(client, username, role):
    return client.post("/api/v1/tenancy/staff/", {"username": username, "email": f"{username}@example.com",
                       "password": PASSWORD, "role": role}, format="json")


def signed_in(username):
    client = APIClient()
    client.force_login(User.objects.get(username=username))
    return client


def test_owner_adds_staff_whose_role_limits_access(businesses):
    a, b = businesses
    response = add_staff(a["client"], "alpha-cashier", "CASHIER")
    assert response.status_code == 201, response.content
    assert Membership.objects.get(user__username="alpha-cashier").organization == a["org"]
    listed = a["client"].get("/api/v1/tenancy/staff/").json()
    assert {m["username"] for m in listed["staff"]} == {"Alpha", "alpha-cashier"}
    assert "Beta" not in str(listed)

    cashier = signed_in("alpha-cashier")
    assert cashier.get("/api/v1/commerce/pos/catalog/").status_code == 200
    assert cashier.post("/api/v1/locations/stacks/", {}, format="json").status_code == 403
    assert cashier.get("/api/v1/tenancy/staff/").status_code == 403
    assert add_staff(cashier, "sneaky", "ADMIN").status_code == 403


def test_staff_cannot_escalate_or_touch_owner_and_suspension_blocks_access(businesses):
    a, b = businesses
    add_staff(a["client"], "alpha-admin", "ADMIN")
    add_staff(a["client"], "alpha-clerk", "INVENTORY")
    admin = signed_in("alpha-admin")
    owner_row = Membership.objects.get(user=a["user"], organization=a["org"])
    clerk_row = Membership.objects.get(user__username="alpha-clerk")
    admin_row = Membership.objects.get(user__username="alpha-admin")

    assert admin.patch(f"/api/v1/tenancy/staff/{owner_row.pk}/", {"status": "SUSPENDED"}, format="json").status_code == 400
    assert admin.patch(f"/api/v1/tenancy/staff/{admin_row.pk}/", {"role": "MANAGER"}, format="json").status_code == 400
    assert admin.patch(f"/api/v1/tenancy/staff/{clerk_row.pk}/", {"role": "ADMIN"}, format="json").status_code == 403
    assert add_staff(admin, "made-admin", "ADMIN").status_code == 403
    assert add_staff(a["client"], "made-owner", "OWNER").status_code == 400

    # Another business cannot see or change this business's staff.
    assert b["client"].patch(f"/api/v1/tenancy/staff/{clerk_row.pk}/", {"status": "SUSPENDED"}, format="json").status_code == 404

    response = admin.patch(f"/api/v1/tenancy/staff/{clerk_row.pk}/", {"status": "SUSPENDED"}, format="json")
    assert response.status_code == 200, response.content
    assert signed_in("alpha-clerk").get("/api/v1/catalog/products/").status_code == 403


def test_duplicate_username_and_weak_password_rejected(businesses):
    a, _ = businesses
    assert add_staff(a["client"], "Beta", "CASHIER").status_code == 400
    weak = a["client"].post("/api/v1/tenancy/staff/", {"username": "weak", "email": "w@example.com", "password": "123", "role": "CASHIER"}, format="json")
    assert weak.status_code == 400 and not User.objects.filter(username="weak").exists()


def test_owner_updates_business_settings(businesses):
    a, b = businesses
    response = a["client"].patch("/api/v1/tenancy/settings/", {"name": "Alpha Traders", "timezone": "Africa/Kampala",
                                 "enabled_modules": ["inventory", "pos"], "receipt_footer": "Thank you"}, format="json")
    assert response.status_code == 200, response.content
    a["org"].refresh_from_db()
    assert a["org"].name == "Alpha Traders" and a["org"].enabled_modules == ["inventory", "pos"]
    assert response.json()["receipt_footer"] == "Thank you"
    assert a["client"].get("/api/v1/mpesa/dashboard/").status_code == 403
    assert a["client"].patch("/api/v1/tenancy/settings/", {"timezone": "Mars/Base"}, format="json").status_code == 400
    b["org"].refresh_from_db()
    assert b["org"].name == "Beta"
    add_staff(a["client"], "alpha-manager", "MANAGER")
    assert signed_in("alpha-manager").patch("/api/v1/tenancy/settings/", {"name": "Hijack"}, format="json").status_code == 403


def test_service_can_be_added_without_existing_product(businesses):
    a, b = businesses
    response = a["client"].post("/api/v1/cyber/services/", {"name": "Printing", "selling_price": "10", "billing_unit": "PER_PAGE",
                                "requires_job": True}, format="json")
    assert response.status_code == 201, response.content
    assert response.json()["name"] == "Printing" and response.json()["selling_price"] == "10.00"
    again = a["client"].post("/api/v1/cyber/services/", {"name": "Printing", "selling_price": "15", "billing_unit": "PER_COPY"}, format="json")
    assert again.status_code == 201, again.content
    with organization_context(a["org"]):
        assert Product.objects.filter(product_type=Product.SERVICE).count() == 2
        assert CyberServiceProfile.objects.count() == 2
    with organization_context(b["org"]):
        assert not CyberServiceProfile.objects.exists()
    bad = a["client"].post("/api/v1/cyber/services/", {"name": "Scan", "selling_price": "-1", "billing_unit": "PER_PAGE"}, format="json")
    assert bad.status_code == 400


def test_outlet_defaults_to_current_branch(businesses):
    a, _ = businesses
    response = a["client"].post("/api/v1/mpesa/outlets/", {"display_name": "Main till"}, format="json")
    assert response.status_code == 201, response.content
    with organization_context(a["org"]):
        assert MpesaOutlet.objects.get().store == a["store"]


def test_single_shelf_creation_validates_zone(businesses):
    a, b = businesses
    base = {"display_name": "Wall shelf", "x": 0, "y": 0, "width": 10, "height": 10}
    assert a["client"].post("/api/v1/locations/shelves/", base, format="json").status_code == 400
    assert a["client"].post("/api/v1/locations/shelves/", {**base, "zone": b["zone"].pk}, format="json").status_code == 400
    response = a["client"].post("/api/v1/locations/shelves/", {**base, "zone": a["zone"].pk}, format="json")
    assert response.status_code == 201, response.content
    with organization_context(a["org"]):
        assert Shelf.objects.filter(display_name="Wall shelf", zone=a["zone"]).exists()
    assert a["client"].post("/api/v1/locations/stacks/", {"zone": 999999}, format="json").status_code == 400
