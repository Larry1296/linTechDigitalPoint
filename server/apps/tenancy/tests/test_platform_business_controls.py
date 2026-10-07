"""The platform administrator switches a business off and on, and deletes a switched-off business for good."""
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.accounting.models import ExpenseCategory, JournalEntry
from apps.accounting.services import record_expense
from apps.catalog.models import Product
from apps.core.models import AuditLog, Store
from apps.inventory.adjustments import adjust_stock
from apps.inventory.models import Movement, StockAdjustment
from apps.inventory.services import complete_sale
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db


def platform_admin():
    user = User.objects.create_user("platform-owner", password="Safe-pass-1848", is_superuser=True, is_staff=True)
    client = APIClient()
    client.force_login(user)
    return client


def path(org):
    return f"/api/v1/tenancy/platform-admin/businesses/{org.pk}/"


def test_a_switched_off_business_is_closed_to_its_staff_until_switched_back_on(businesses):
    a, b = businesses
    admin = platform_admin()
    assert a["client"].get("/api/v1/catalog/products/").status_code == 200
    off = admin.patch(path(a["org"]), {"active": False, "note": "Fraud report"}, format="json")
    assert off.status_code == 200, off.content
    assert off.json()["active"] is False
    assert a["client"].get("/api/v1/catalog/products/").status_code == 403
    me = a["client"].get("/api/v1/auth/me/").json()
    assert me["organization"] is None and me["switched_off_businesses"] == ["Alpha"]
    assert b["client"].get("/api/v1/catalog/products/").status_code == 200
    assert admin.get("/api/v1/tenancy/platform-admin/overview/").json()["summary"]["switched_off"] == 1
    with organization_context(a["org"]):
        assert AuditLog.objects.filter(action="BUSINESS_DEACTIVATED").count() == 1
    assert admin.patch(path(a["org"]), {"active": True}, format="json").json()["active"] is True
    assert a["client"].get("/api/v1/catalog/products/").status_code == 200


def test_only_the_platform_admin_can_switch_off_or_delete(businesses):
    a, b = businesses
    assert a["client"].patch(path(b["org"]), {"active": False}, format="json").status_code == 403
    assert a["client"].delete(path(b["org"]), {"confirm_name": "Beta"}, format="json").status_code == 403
    assert Organization.objects.get(pk=b["org"].pk).active


def test_deleting_needs_the_business_switched_off_and_its_name_typed(businesses):
    a, _ = businesses
    admin = platform_admin()
    assert admin.delete(path(a["org"]), {"confirm_name": "Alpha"}, format="json").status_code == 400
    admin.patch(path(a["org"]), {"active": False}, format="json")
    assert admin.delete(path(a["org"]), {"confirm_name": "alpha"}, format="json").status_code == 400
    assert Organization.objects.filter(pk=a["org"].pk).exists()


def test_deleting_removes_the_business_and_its_books_and_leaves_others_untouched(businesses):
    a, b = businesses
    with organization_context(a["org"]):
        complete_sale(lines=[{"variant": a["variant"], "quantity": 1}], channel="POS", number="S-1", user=a["user"])
        record_expense(user=a["user"], category=ExpenseCategory.objects.create(name="Rent"), unit="SHOP", method="CASH",
                       amount=200, description="Rent", key="rent")
        adjust_stock(user=a["user"], variant_id=a["variant"].pk, shelf_id=a["shelf"].pk, expected_quantity=4, counted_quantity=6,
                     reason="Opening stock correction", notes="Found two more on the shelf during the count.", reference="C-1",
                     idempotency_key="c-1", confirmed=True, lot_id=a["lot"].pk)
        assert JournalEntry.objects.exists() and StockAdjustment.objects.exists()
    with organization_context(b["org"]):
        complete_sale(lines=[{"variant": b["variant"], "quantity": 1}], channel="POS", number="S-1", user=b["user"])
        beta_journals = JournalEntry.objects.count()
    admin = platform_admin()
    admin.patch(path(a["org"]), {"active": False}, format="json")
    response = admin.delete(path(a["org"]), {"confirm_name": "Alpha"}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["deleted"] == "Alpha" and response.json()["records"] > 0
    assert not Organization.objects.filter(pk=a["org"].pk).exists()
    assert not Membership.objects.filter(organization_id=a["org"].pk).exists()
    assert not OrganizationSubscription.objects.filter(organization_id=a["org"].pk).exists()
    with organization_context(a["org"]):
        assert not Store.objects.exists() and not Product.objects.exists() and not JournalEntry.objects.exists()
        assert not Movement.objects.exists()
    with organization_context(b["org"]):
        assert JournalEntry.objects.count() == beta_journals and Product.objects.exists()
    assert User.objects.filter(pk=a["user"].pk).exists()  # people keep their accounts
    # The books are still protected for everyone else.
    with organization_context(b["org"]), pytest.raises(Exception):
        JournalEntry.objects.all().delete()
