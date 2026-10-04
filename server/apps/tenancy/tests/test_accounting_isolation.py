"""Accounting reports and drill-downs never cross businesses or unauthorised branches."""
from decimal import Decimal
import pytest
from apps.core.models import Store
from apps.inventory.models import Shelf, Zone
from apps.inventory.services import complete_sale, receive_stock
from apps.tenancy.context import branch_context, organization_context
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db


def test_two_businesses_and_two_branches_cannot_see_each_others_accounts(businesses):
    a, b = businesses
    with organization_context(a["org"]):
        a_sale = complete_sale(lines=[{"variant": a["variant"], "quantity": 1, "unit_price": Decimal("150")}], channel="POS", number="A-1", user=a["user"])
        second = Store.objects.create(name="Alpha second branch")
        with branch_context(second.pk):
            zone = Zone.objects.create(store=second, name="Stall", code="STALL")
            shelf = Shelf.objects.create(zone=zone, code="S1", display_name="Crate", x=0, y=0, width=1, height=1)
            receive_stock(variant=a["variant"], placements=[{"shelf": shelf, "quantity": 2}], unit_cost=60, reference="STALL", user=a["user"])
            complete_sale(lines=[{"variant": a["variant"], "quantity": 1, "unit_price": Decimal("200")}], channel="POS", number="A-2", user=a["user"])
    with organization_context(b["org"]):
        complete_sale(lines=[{"variant": b["variant"], "quantity": 1}], channel="POS", number="B-1", user=b["user"])
    with organization_context(a["org"]):
        item = a_sale.items.get().pk

    explained = a["client"].get(f"/api/v1/accounting/explain/sale-items/{item}/")
    assert explained.status_code == 200 and Decimal(str(explained.json()["line"]["actual_price"])) == 150
    assert b["client"].get(f"/api/v1/accounting/explain/sale-items/{item}/").status_code == 404

    main = a["client"].get("/api/v1/accounting/statements/", {"view": "units", "branch": a["store"].pk}).json()
    stall = a["client"].get("/api/v1/accounting/statements/", {"view": "units", "branch": second.pk}).json()
    assert Decimal(main["profit_and_loss"]["units"][0]["revenue"]) == 150
    assert Decimal(stall["profit_and_loss"]["units"][0]["revenue"]) == 200
    assert a["client"].get("/api/v1/accounting/statements/", {"branch": b["store"].pk}).status_code == 403
    other = b["client"].get("/api/v1/accounting/statements/", {"view": "accounting"}).json()
    assert "A-1" not in str(other) and "A-2" not in str(other)
    assert Decimal(other["profit_and_loss"]["revenue"]) == 100
    assert b["client"].get("/api/v1/accounting/statements/accounts/4000/", {"branch": a["store"].pk}).status_code == 403
