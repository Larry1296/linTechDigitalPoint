"""Hotels: an eatery's menu sells without counting plates and its kitchen's use is the cost of meals; a hotel's guests are
booked, checked in, charged each night, charge food to their room, pay in advance and check out with nothing left over."""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounting.models import CashEntry, JournalLine
from apps.commerce.models import Sale
from apps.core.models import Store
from apps.hotel import menu, rooms
from apps.hotel.models import Room, Stay, StayCharge
from apps.inventory.services import complete_stock_receipt
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal
TZ = timezone.get_default_timezone()


def at(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 10, day, hour, minute), TZ)


@pytest.fixture
def clock(monkeypatch):
    """clock(day, hour) makes that moment now (October 2026)."""
    def move(day, hour, minute=0):
        moment = at(day, hour, minute)
        monkeypatch.setattr(timezone, "now", lambda: moment)
        monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: timezone.localtime(moment).date())
    move(5, 14)
    return move


@pytest.fixture
def hotel():
    owner = User.objects.create_user("hotel-owner", password="Safe-pass-1848", first_name="Wanjiru")
    org = Organization.objects.create(name="Mlima Hotel", slug="mlima", owner=owner, sector="hotel_rooms",
                                      enabled_modules=["rooms", "menu", "inventory", "pos", "customers", "expenses", "reports"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    cashier = User.objects.create_user("cashier", password="Safe-pass-1848")
    Membership.objects.create(user=cashier, organization=org, role="CASHIER")
    client, till = APIClient(), APIClient()
    client.force_authenticate(owner)
    till.force_authenticate(cashier)
    with organization_context(org):
        Store.objects.create(name="Main")
        double = rooms.add_room_type(name="Double room", rate=3000)
        room = rooms.add_room(number="101", room_type=double)
        other = rooms.add_room(number="102", room_type=double)
        chapati = menu.add_item(name="Chapati", price=30)
        flour = menu.add_ingredient(name="Wheat flour", unit="kg")
        complete_stock_receipt(supplier_name="Unga", external_reference="INV-1", received_at=timezone.now() - timedelta(days=30),
                               lines=[{"variant_id": flour.variant.pk, "received_quantity": "20", "unit_cost": "150"}], user=owner)
    return SimpleNamespace(org=org, owner=owner, client=client, till=till, double=double, room=room, other=other, chapati=chapati, flour=flour)


def books(code):
    rows = JournalLine.objects.filter(account__code=code).aggregate(d=Sum("debit"), c=Sum("credit"))
    return (rows["d"] or 0) - (rows["c"] or 0)


def walk_in(hotel, departure_day=7, **extra):
    response = hotel.client.post("/api/v1/hotel/stays/", {"room": hotel.room.pk, "departure": f"2026-10-{departure_day:02d}",
                                                         "guest_name": "Otieno Okoth", "phone": "0711000111", "id_number": "23456789",
                                                         "check_in_now": True, **extra}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


# The eatery ---------------------------------------------------------------------------------------------------------

def test_a_meal_sells_at_the_till_without_stock_and_its_income_is_the_menus(hotel):
    catalog = hotel.till.get("/api/v1/commerce/pos/catalog/").json()
    names = {row["product_name"] for row in catalog}
    assert "Chapati" in names and "Wheat flour" not in names and "Double room" not in names  # cooked, and sold at the desk
    checkout = hotel.till.post("/api/v1/commerce/pos/checkouts/", {"items": [{"variant_id": hotel.chapati.variant.pk, "quantity": 4}],
                                                                  "idempotency_key": uuid4().hex}, format="json")
    assert checkout.status_code == 201, checkout.content
    paid = hotel.till.post(f"/api/v1/commerce/pos/checkouts/{checkout.json()['id']}/pay/", {"method": "CASH", "cash_given": "200"}, format="json")
    assert paid.status_code == 201, paid.content
    with organization_context(hotel.org):
        assert Sale.objects.get().total == D("120")
        assert books("4030") == D("-120") and books("4020") == 0


def test_a_dish_that_has_run_out_leaves_the_till_until_it_is_back(hotel):
    response = hotel.till.patch(f"/api/v1/hotel/menu/{hotel.chapati.pk}/", {"available": False}, format="json")
    assert response.status_code == 200, response.content
    assert "Chapati" not in {row["product_name"] for row in hotel.till.get("/api/v1/commerce/pos/catalog/").json()}
    assert hotel.till.patch(f"/api/v1/hotel/menu/{hotel.chapati.pk}/", {"price": "50"}, format="json").status_code == 403  # the menu is the owner's


@pytest.mark.parametrize("line,used", [({"quantity": "3"}, D("3")), ({"left": "16"}, D("4"))])
def test_what_the_kitchen_used_is_the_cost_of_meals(hotel, line, used):
    way = "USED" if "quantity" in line else "COUNTED"
    response = hotel.client.post("/api/v1/hotel/kitchen/use/", {"way": way, "lines": [{"ingredient_id": hotel.flour.pk, **line}]}, format="json")
    assert response.status_code == 201, response.content
    assert D(response.json()["total_cost"]) == used * 150
    with organization_context(hotel.org):
        assert menu.in_store(hotel.flour.variant) == 20 - used
        assert books("5020") == used * 150 and books("1200") == (20 - used) * 150


def test_the_kitchen_cannot_use_more_than_the_store_holds(hotel):
    response = hotel.client.post("/api/v1/hotel/kitchen/use/", {"way": "COUNTED", "lines": [{"ingredient_id": hotel.flour.pk, "left": "25"}]}, format="json")
    assert response.status_code == 400 and "Receive stock" in str(response.json())


# Nights -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("came,now,nights", [
    ((5, 14), (5, 15), 1),          # on arrival
    ((5, 14), (7, 9), 2),           # Monday afternoon to Wednesday morning
    ((5, 14), (7, 10, 30), 3),      # still in after the check-out time
    ((6, 2), (6, 9), 1),            # came in the small hours
    ((6, 2), (6, 10, 30), 2),       # and stayed past the check-out time
])
def test_a_night_is_charged_on_arrival_and_each_time_the_check_out_time_passes(hotel, clock, came, now, nights):
    with organization_context(hotel.org):
        stay = Stay(status=Stay.IN, checked_in_at=at(*came))
        assert rooms.nights_due(stay, at(*now)) == nights


def test_a_walk_in_pays_the_first_night_and_later_nights_are_charged_once_each(hotel, clock):
    stay = walk_in(hotel)
    assert stay["status"] == "IN" and D(stay["bill"]["owing"]) == D("3000")
    clock(6, 11)
    call_command("charge_room_nights")
    call_command("charge_room_nights")
    detail = hotel.client.get(f"/api/v1/hotel/stays/{stay['id']}/").json()
    assert [charge["night"] for charge in detail["bill"]["charges"]] == ["2026-10-05", "2026-10-06"]
    assert D(detail["bill"]["owing"]) == D("6000")
    with organization_context(hotel.org):
        assert books("4040") == D("-6000") and books("1100") == D("6000")


# Money --------------------------------------------------------------------------------------------------------------

def test_a_deposit_pays_the_nights_and_food_charged_to_the_room_and_the_rest_is_given_back(hotel, clock):
    stay = walk_in(hotel, paid="10000", method="MPESA", reference="RKT123ABC")
    assert D(stay["bill"]["held"]) == D("7000") and D(stay["bill"]["owing"]) == 0
    # Lunch charged to the room at the till.
    checkout = hotel.till.post("/api/v1/commerce/pos/checkouts/", {"items": [{"variant_id": hotel.chapati.variant.pk, "quantity": 10}],
                                                                  "idempotency_key": uuid4().hex}, format="json").json()
    guests = hotel.till.get("/api/v1/hotel/stays/in-house/").json()
    assert guests == [{"id": stay["id"], "number": stay["number"], "room": "101", "guest": "Otieno Okoth"}]
    paid = hotel.till.post(f"/api/v1/commerce/pos/checkouts/{checkout['id']}/pay/", {"method": "ROOM", "stay_id": stay["id"]}, format="json")
    assert paid.status_code == 201, paid.content
    hotel.client.post(f"/api/v1/hotel/stays/{stay['id']}/extras/", {"description": "Laundry", "amount": "500"}, format="json")
    clock(6, 11)  # a second night
    bill = hotel.client.get(f"/api/v1/hotel/stays/{stay['id']}/").json()["bill"]
    assert D(bill["total"]) == D("3000") + D("300") + D("500") + D("3000")
    assert D(bill["held"]) == D("10000") - D("6800") and D(bill["owing"]) == 0
    assert [line["name"] for charge in bill["charges"] for line in charge["lines"]][2] == "Laundry"
    refused = hotel.client.post(f"/api/v1/hotel/stays/{stay['id']}/check-out/", {}, format="json")
    assert refused.status_code == 400 and "3,200.00 left" in str(refused.json())
    out = hotel.client.post(f"/api/v1/hotel/stays/{stay['id']}/check-out/", {"give_back_by": "CASH"}, format="json")
    assert out.status_code == 200, out.content
    assert out.json()["status"] == "OUT" and D(out.json()["bill"]["held"]) == 0
    with organization_context(hotel.org):
        assert Room.objects.get(pk=hotel.room.pk).condition == Room.DIRTY
        assert books("2300") == 0 and books("1100") == 0  # nothing owed either way
        assert books("4040") == D("-6500") and books("4030") == D("-300")
        # Money in: 10,000 by M-Pesa, 3,200 given back in cash; using the deposit moved no money.
        assert CashEntry.objects.aggregate(v=Sum("amount"))["v"] == D("6800")
        assert books("1020") == D("10000") and books("1000") == D("-3200")


def test_a_guest_who_still_owes_pays_on_leaving(hotel, clock):
    stay = walk_in(hotel)
    clock(7, 9)
    refused = hotel.client.post(f"/api/v1/hotel/stays/{stay['id']}/check-out/", {}, format="json")
    assert refused.status_code == 400 and "still owes 6,000.00" in str(refused.json())
    out = hotel.client.post(f"/api/v1/hotel/stays/{stay['id']}/check-out/", {"payment": {"amount": "6000", "method": "CASH"}}, format="json")
    assert out.status_code == 200, out.content
    assert D(out.json()["bill"]["balance"]) == 0
    with organization_context(hotel.org):
        assert books("1000") == D("6000") and books("1100") == 0


def test_a_cancelled_booking_keeps_its_deposit_when_the_owner_says_so(hotel, clock):
    booked = hotel.client.post("/api/v1/hotel/stays/", {"room": hotel.room.pk, "arrival": "2026-10-10", "departure": "2026-10-12",
                                                       "guest_name": "Achieng", "paid": "1500", "method": "CASH"}, format="json")
    assert booked.status_code == 201, booked.content
    stay = booked.json()
    assert stay["status"] == "BOOKED" and D(stay["bill"]["held"]) == D("1500")
    cancelled = hotel.client.post(f"/api/v1/hotel/stays/{stay['id']}/cancel/", {"keep_paid": True, "reason": "Plans changed"}, format="json")
    assert cancelled.status_code == 200, cancelled.content
    assert cancelled.json()["status"] == "CANCELLED" and D(cancelled.json()["bill"]["held"]) == 0
    with organization_context(hotel.org):
        assert books("4040") == D("-1500") and books("2300") == 0


# Bookings -----------------------------------------------------------------------------------------------------------

def test_a_room_is_never_booked_twice_for_the_same_night(hotel, clock):
    walk_in(hotel, departure_day=8)
    clash = hotel.client.post("/api/v1/hotel/stays/", {"room": hotel.room.pk, "arrival": "2026-10-07", "departure": "2026-10-09",
                                                      "guest_name": "Kamau"}, format="json")
    assert clash.status_code == 400 and "Room 101 is taken" in str(clash.json())
    later = hotel.client.post("/api/v1/hotel/stays/", {"room": hotel.room.pk, "arrival": "2026-10-08", "departure": "2026-10-09",
                                                      "guest_name": "Kamau"}, format="json")
    assert later.status_code == 201, later.content


def test_the_board_shows_who_is_in_who_arrives_and_what_is_free(hotel, clock):
    walk_in(hotel)
    hotel.client.post("/api/v1/hotel/stays/", {"room": hotel.other.pk, "arrival": "2026-10-05", "departure": "2026-10-06",
                                               "guest_name": "Njeri"}, format="json")
    board = hotel.client.get("/api/v1/hotel/rooms/").json()
    states = {room["number"]: room["state"] for room in board["rooms"]}
    assert states == {"101": "OCCUPIED", "102": "BOOKED"}
    assert board["counts"]["arrivals"] == 1 and board["counts"]["OCCUPIED"] == 1


def test_a_returning_guest_is_the_same_customer(hotel, clock):
    first = walk_in(hotel, departure_day=6)
    second = hotel.client.post("/api/v1/hotel/stays/", {"room": hotel.other.pk, "arrival": "2026-10-20", "departure": "2026-10-21",
                                                       "guest_name": "Otieno O.", "phone": "0711000111"}, format="json").json()
    assert second["guest_id"] == first["guest_id"]


# Setting up ---------------------------------------------------------------------------------------------------------

def test_a_hotel_with_rooms_starts_with_its_rooms_and_restaurant_as_two_parts(hotel):
    from apps.accounting.money_mode import business_parts, part_names
    with organization_context(hotel.org):
        assert business_parts(hotel.org) == ["SHOP", "CYBER"]
        assert part_names(hotel.org)["CYBER"] == "Rooms" and part_names(hotel.org)["SHOP"] == "Restaurant & bar"
