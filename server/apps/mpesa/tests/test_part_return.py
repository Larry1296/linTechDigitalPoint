"""Shop money put into the agency when its float was low is lent: the agency owes it back and returns it later, out of
its cash or its float, into one of the shop's places. Each part's own money counts it as the shop's all along."""
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.models import CashEntry
from apps.mpesa.models import MpesaSession
from apps.mpesa.tests.test_parts_own_money import lintech, open_shift, sell  # noqa: F401
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
D = Decimal


def move(shop, shift, kind, value, place, key, **extra):
    return shop.client.post("/api/v1/mpesa/transactions/", {"session": shift, "transaction_type": kind, "amount": str(value),
                            "paid_by": place, "idempotency_key": key, **extra}, format="json")


def owed(shop):
    rows = shop.client.get("/api/v1/mpesa/dashboard/").json()["owed_to_parts"]
    return {row["part"]: D(str(row["amount"])) for row in rows}


def own_money(shop, part):
    return D(str(shop.client.get(f"/api/v1/inventory/parts/{part}/").json()["money"]["amount"]))


def test_shop_money_lent_to_the_float_is_owed_and_returned(lintech):
    shop = lintech
    sell(shop, 3000)                                           # the shop's cash in the drawer
    shift = open_shift(shop, 1000, 500).json()["id"]
    shop_before, agency_before = own_money(shop, "SHOP"), own_money(shop, "MPESA")
    assert move(shop, shift, "FLOAT_TOPUP", 2000, "SHOP:CASH", "t1").status_code == 201
    assert owed(shop) == {"SHOP": D("2000.00")}
    # The shop's money is still the shop's, and the agency's own money did not grow by it.
    assert own_money(shop, "SHOP") == shop_before
    assert own_money(shop, "MPESA") == agency_before
    # More than owed is refused.
    too_much = move(shop, shift, "PART_RETURN", 2500, "SHOP:CASH", "r0", return_from="FLOAT")
    assert too_much.status_code == 400 and "owes" in str(too_much.content)
    # Part back out of the float into the shop's till, the rest out of the agency's cash into the drawer.
    assert move(shop, shift, "PART_RETURN", 1500, "SHOP:MPESA", "r1", return_from="FLOAT").status_code == 201
    assert owed(shop) == {"SHOP": D("500.00")}
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert (D(str(board["cash"])), D(str(board["float"]))) == (D("1000.00"), D("1000.00"))
    assert move(shop, shift, "PART_RETURN", 500, "SHOP:CASH", "r2", return_from="CASH").status_code == 201
    assert owed(shop) == {}
    with organization_context(shop.org):
        assert CashEntry.objects.filter(business_unit="SHOP", kind="TRANSFER").count() == 3
    assert own_money(shop, "SHOP") == shop_before
    assert own_money(shop, "MPESA") == agency_before  # it held the shop's money and gave all of it back


def test_returning_needs_the_money_and_undoing_puts_it_owed_again(lintech):
    shop = lintech
    sell(shop, 3000)
    shift = open_shift(shop, 100, 0).json()["id"]
    assert move(shop, shift, "FLOAT_TOPUP", 2000, "SHOP:CASH", "t1").status_code == 201
    short = move(shop, shift, "PART_RETURN", 1000, "SHOP:CASH", "r0", return_from="CASH")
    assert short.status_code == 400 and "cash is only" in str(short.content)
    back = move(shop, shift, "PART_RETURN", 1000, "SHOP:CASH", "r1", return_from="FLOAT").json()
    # The top-up cannot be undone while part of it is returned; the return can.
    listed = shop.client.get(f"/api/v1/mpesa/transactions/?session={shift}").json()
    topup = next(t for t in listed.get("results", listed) if t["transaction_type"] == "FLOAT_TOPUP") if isinstance(listed, dict) else \
        next(t for t in listed if t["transaction_type"] == "FLOAT_TOPUP")
    refused = shop.client.post(f"/api/v1/mpesa/transactions/{topup['id']}/reverse/", {"reason": "wrong", "idempotency_key": "x1"}, format="json")
    assert refused.status_code == 400, refused.content
    undone = shop.client.post(f"/api/v1/mpesa/transactions/{back['id']}/reverse/", {"reason": "wrong", "idempotency_key": "x2"}, format="json")
    assert undone.status_code in (200, 201), undone.content
    assert owed(shop) == {"SHOP": D("2000.00")}


def test_shop_money_already_in_the_counted_float_is_owed_without_changing_the_float(lintech):
    shop = lintech
    sell(shop, 910)                                      # the books expect 910 of the shop's in the drawer
    shift = open_shift(shop, 1000, 4939).json()["id"]    # 508 of it was already put on the line and counted
    agency_before = own_money(shop, "MPESA")
    assert move(shop, shift, "FLOAT_TOPUP", 508, "SHOP:CASH", "t1", already_in_float=True).status_code == 201
    board = shop.client.get("/api/v1/mpesa/dashboard/").json()
    assert D(str(board["float"])) == D("4939.00")
    assert owed(shop) == {"SHOP": D("508.00")}
    assert own_money(shop, "MPESA") == agency_before - D("508.00")
    with organization_context(shop.org):
        from apps.accounting.money_check import places
        drawer = next(p for p in places() if p["method"] == "CASH")
        assert next(r["amount"] for r in drawer["by_part"] if r["unit"] == "SHOP") == D("402.00")
