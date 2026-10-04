"""Branches can be added, renamed and removed; the main branch and any branch with history stay."""
import pytest
from django.contrib.auth.models import User
from apps.core.models import Store
from apps.inventory.models import Shelf, Zone
from apps.inventory.services import create_shelf_stack, receive_stock
from apps.tenancy.context import organization_context
from apps.tenancy.models import BranchMembership
from apps.tenancy.tests.test_business_admin import add_staff, signed_in
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db


def add_branch(client, name="Kiandas stall"):
    response = client.post("/api/v1/tenancy/branches/", {"name": name, "address": "Kiandas"}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def test_main_branch_details_change_but_it_cannot_be_deleted(businesses):
    a, _ = businesses
    main = a["client"].get("/api/v1/tenancy/branches/").json()
    assert [row["is_main"] for row in main] == [True]
    response = a["client"].patch(f"/api/v1/tenancy/branches/{a['store'].pk}/",
                                 {"name": "Town branch", "address": "Moi Avenue, Nairobi", "phone": "0700000000"}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["address"] == "Moi Avenue, Nairobi" and response.json()["is_main"]
    with organization_context(a["org"]):
        assert Store.objects.get(pk=a["store"].pk).name == "Town branch"
    response = a["client"].delete(f"/api/v1/tenancy/branches/{a['store'].pk}/")
    assert response.status_code == 400 and "main branch" in response.json()["detail"]


def test_unused_branch_is_deleted_with_its_empty_shelves_and_assignments(businesses):
    a, _ = businesses
    branch = add_branch(a["client"])
    assert branch["is_main"] is False
    add_staff(a["client"], "stall-cashier", "CASHIER")
    with organization_context(a["org"]):
        store = Store.objects.get(pk=branch["id"])
        BranchMembership.objects.create(user=User.objects.get(username="stall-cashier"), store=store)
        zone = Zone.objects.create(store=store, code="STALL", name="Stall")
        create_shelf_stack(zone=zone, user=a["user"], display_name="Veg rack", x=0, y=0, width=100, height=100,
                           depth=30, level_definitions=[{"compartments": 2}])
    response = a["client"].delete(f"/api/v1/tenancy/branches/{branch['id']}/")
    assert response.status_code == 204, response.content
    with organization_context(a["org"]):
        assert not Store.objects.filter(pk=branch["id"]).exists()
        assert not Zone.objects.filter(pk=zone.pk).exists()
        assert not BranchMembership.objects.filter(store_id=branch["id"]).exists()
        assert Store.objects.filter(pk=a["store"].pk).exists()


def test_branch_with_stock_history_cannot_be_deleted(businesses):
    a, _ = businesses
    branch = add_branch(a["client"])
    with organization_context(a["org"]):
        zone = Zone.objects.create(store_id=branch["id"], code="STALL", name="Stall")
        shelf = Shelf.objects.create(zone=zone, code="S1", display_name="Crate", x=0, y=0, width=10, height=10)
        receive_stock(variant=a["variant"], placements=[{"shelf": shelf, "quantity": 3}], unit_cost=40, reference="STALL-1", user=a["user"])
    response = a["client"].delete(f"/api/v1/tenancy/branches/{branch['id']}/")
    assert response.status_code == 400
    assert "stock" in response.json()["detail"] and "ledger entries" in response.json()["detail"]
    with organization_context(a["org"]):
        assert Store.objects.filter(pk=branch["id"]).exists()


def test_only_owner_or_admin_deletes_and_other_businesses_are_untouchable(businesses):
    a, b = businesses
    branch = add_branch(a["client"])
    add_staff(a["client"], "alpha-manager", "MANAGER")
    manager = signed_in("alpha-manager")
    assert manager.patch(f"/api/v1/tenancy/branches/{branch['id']}/", {"address": "Market lane"}, format="json").status_code == 200
    assert manager.delete(f"/api/v1/tenancy/branches/{branch['id']}/").status_code == 403
    assert b["client"].patch(f"/api/v1/tenancy/branches/{branch['id']}/", {"name": "Taken"}, format="json").status_code == 404
    assert b["client"].delete(f"/api/v1/tenancy/branches/{branch['id']}/").status_code == 404
    with organization_context(a["org"]):
        assert Store.objects.get(pk=branch["id"]).name == "Kiandas stall"
