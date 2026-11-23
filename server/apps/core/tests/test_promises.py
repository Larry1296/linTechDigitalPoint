"""Customer promises: what a customer asked for, what they were promised and by when, kept until closed as met or not."""
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounting.models import CashEntry, JournalEntry
from apps.core.models import CustomerPromise, Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription
from apps.tenancy.permissions import employee_permission

pytestmark = pytest.mark.django_db


def business():
    owner = User.objects.create_user(f"owner{Organization.objects.count()}", password="Safe-pass-1848")
    org = Organization.objects.create(name="Shop", slug=f"shop-{Organization.objects.count()}", owner=owner, enabled_modules=["pos", "inventory"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
    client = APIClient()
    client.force_login(owner)
    return org, client


def promise(**extra):
    return {"customer_name": "Wanjiru", "phone": "0712 345 678", "wanted": "iPhone 13 screen protectors",
            "promised": "Check with the supplier and call her back", "due_at": (timezone.now() + timedelta(days=3)).isoformat(), **extra}


def test_a_promise_is_kept_open_soonest_first_with_the_time_it_was_written_set_by_itself():
    org, client = business()
    before = timezone.now()
    made = client.post("/api/v1/promises/", promise(), format="json")
    assert made.status_code == 201
    soon = client.post("/api/v1/promises/", promise(wanted="Type-C earphones", due_at=(timezone.now() + timedelta(hours=3)).isoformat()), format="json").json()
    assert [p["wanted"] for p in soon["open"]] == ["Type-C earphones", "iPhone 13 screen protectors"]  # soonest first
    assert [p["state"] for p in soon["open"]] == ["soon", "later"] and soon["soon"] == 1 and soon["late"] == 0
    first = soon["open"][1]
    assert first["status"] == "OPEN" and first["closed_at"] is None and first["created_by_name"].startswith("owner")
    assert timezone.datetime.fromisoformat(first["created_at"]) >= before
    # The time it was written cannot be typed in.
    sneaky = client.post("/api/v1/promises/", promise(created_at="2020-01-01T00:00:00Z", status="MET"), format="json").json()
    newest = max(sneaky["open"], key=lambda p: p["id"])
    assert newest["created_at"][:4] != "2020" and newest["status"] == "OPEN"
    with organization_context(org):
        assert not CashEntry.objects.exists() and not JournalEntry.objects.exists()
    other_org, other = business()
    assert other.get("/api/v1/promises/").json()["open"] == []  # each business's own promises


def test_what_a_promise_needs_and_a_time_already_gone_is_refused():
    _, client = business()
    for missing in ("phone", "wanted", "promised", "due_at"):
        assert client.post("/api/v1/promises/", promise(**{missing: ""}), format="json").status_code == 400, missing
    assert client.post("/api/v1/promises/", promise(phone="call me"), format="json").status_code == 400
    assert client.post("/api/v1/promises/", promise(phone="0712"), format="json").status_code == 400
    assert client.post("/api/v1/promises/", promise(phone="+254 712 345 678"), format="json").status_code == 201
    late = client.post("/api/v1/promises/", promise(due_at=(timezone.now() - timedelta(days=1)).isoformat()), format="json")
    assert late.status_code == 400 and "due_at" in late.json().get("errors", late.json())
    assert client.post("/api/v1/promises/", promise(customer_name=""), format="json").status_code == 201  # the name is optional


def test_closing_a_promise_archives_it_with_when_and_how_and_it_can_be_opened_again():
    _, client = business()
    data = client.post("/api/v1/promises/", promise(), format="json").json()
    pk = data["open"][0]["id"]
    data = client.patch(f"/api/v1/promises/{pk}/", {"status": "MET", "outcome": "Called her, she came for two"}, format="json").json()
    assert data["open"] == [] and data["met"] == 1
    done = data["done"][0]
    assert done["state"] == "done" and done["closed_at"] and done["outcome"] == "Called her, she came for two"
    data = client.patch(f"/api/v1/promises/{pk}/", {"status": "OPEN"}, format="json").json()
    assert data["open"][0]["closed_at"] is None and data["done"] == []
    data = client.patch(f"/api/v1/promises/{pk}/", {"status": "NOT_MET", "outcome": "Supplier has none"}, format="json").json()
    assert data["not_met"] == 1 and data["met"] == 0
    assert client.patch(f"/api/v1/promises/{pk}/", {"status": "MAYBE"}, format="json").status_code == 400
    # Pushing the time on an existing promise is allowed even to a time that has gone (it is then late).
    client.patch(f"/api/v1/promises/{pk}/", {"status": "OPEN"}, format="json")
    data = client.patch(f"/api/v1/promises/{pk}/", {"due_at": (timezone.now() - timedelta(hours=1)).isoformat()}, format="json").json()
    assert data["open"][0]["state"] == "late" and data["late"] == 1
    assert client.delete(f"/api/v1/promises/{pk}/").json()["open"] == []


def test_the_dashboard_is_reminded_of_open_promises_due_within_a_day_or_late():
    org, client = business()
    client.post("/api/v1/promises/", promise(wanted="Later one"), format="json")
    client.post("/api/v1/promises/", promise(wanted="Soon one", due_at=(timezone.now() + timedelta(hours=5)).isoformat()), format="json")
    closed = client.post("/api/v1/promises/", promise(wanted="Closed one", due_at=(timezone.now() + timedelta(hours=1)).isoformat()), format="json").json()
    client.patch(f"/api/v1/promises/{next(p['id'] for p in closed['open'] if p['wanted'] == 'Closed one')}/", {"status": "MET"}, format="json")
    with organization_context(org):
        late = CustomerPromise.objects.get(wanted="Later one")
        CustomerPromise.objects.create(customer_name="", phone="0700000000", wanted="Late one", promised="Call",
                                       due_at=timezone.now() - timedelta(hours=2))
    due = client.get("/api/v1/promises/due/").json()
    assert [(p["wanted"], p["state"]) for p in due["due"]] == [("Late one", "late"), ("Soon one", "soon")]
    assert due["soon_hours"] == 24 and late.status == "OPEN"


def test_whoever_serves_customers_records_promises_but_only_the_owner_removes_them():
    assert all(employee_permission(f"core.{code}_customerpromise", ["sales"]) for code in ("view", "add", "change"))
    assert not employee_permission("core.delete_customerpromise", ["sales"])
    assert not employee_permission("core.view_customerpromise", ["mpesa"])
