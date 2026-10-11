"""Chama management: setting up, who has paid, fines, excuses, turns, and that the shop's books are never touched."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounting.models import CashEntry, JournalEntry
from apps.core.models import Store
from apps.chama import services
from apps.chama.models import Chama, ChamaDue, ChamaMember
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription, SubscriptionPlan

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 6)


@pytest.fixture
def on(monkeypatch):
    """Move the business's calendar: on(day) makes `day` today."""
    def move(day):
        monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: day)
    move(TODAY)
    return move


def members(*names):
    return [{"full_name": name, "id_number": f"{20000000 + index}", "phone": f"07123450{index:02d}",
             "role": "TREASURER" if index == 0 else "MEMBER"} for index, name in enumerate(names)]


def setup_data(**overrides):
    return {"name": "Umoja Chama", "contribution_amount": "500", "frequency": "WEEKLY", "start_date": str(TODAY), "grace_days": 2,
            "fine_amount": "50", "members": members("Larry Musau", "Mary Achieng", "John Kamau"), **overrides}


def business(modules=None, plan=None, role="OWNER"):
    owner = User.objects.create_user(f"owner{Organization.objects.count()}", password="Safe-pass-1848", first_name="Larry", last_name="Musau")
    org = Organization.objects.create(name="Shop", slug=f"shop-{Organization.objects.count()}", owner=owner,
                                      enabled_modules=modules if modules is not None else ["pos", "inventory"])
    Membership.objects.create(user=owner, organization=org, role=role)
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE", plan=plan)
    with organization_context(org):
        Store.objects.create(name="Main")
    client = APIClient()
    client.force_login(owner)
    return org, owner, client


def make(org, owner, **overrides):
    from apps.chama.api import ChamaInput
    form = ChamaInput(data=setup_data(**overrides))
    form.is_valid(raise_exception=True)
    with organization_context(org):
        return services.create_chama(user=owner, data=form.validated_data)


def board(org, chama):
    """{member name: (paid, status, fine)} for the current period, as the treasurer sees it."""
    from apps.chama.api import chama_detail
    with organization_context(org):
        data = chama_detail(services.sync(chama), timezone.localdate())
    return {m["full_name"]: (m["this_period"]["paid"], m["this_period"]["status"]) for m in data["members"] if m["this_period"]}, data


# --- Schedule ---------------------------------------------------------------------------------------------------

def test_contribution_dates_follow_the_chosen_frequency():
    monthly = Chama(frequency="MONTHLY", start_date=date(2026, 1, 31))
    assert [services.period_date(monthly, i) for i in range(4)] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    assert services.period_index(monthly, date(2026, 3, 30)) == 1 and services.period_index(monthly, date(2026, 3, 31)) == 2
    assert services.period_index(monthly, date(2026, 1, 30)) == -1
    weekly = Chama(frequency="WEEKLY", start_date=TODAY)
    assert services.periods_between(weekly, None, TODAY + timedelta(days=15)) == [TODAY, TODAY + timedelta(days=7), TODAY + timedelta(days=14)]
    daily = Chama(frequency="DAILY", start_date=TODAY)
    assert services.is_period_date(daily, TODAY + timedelta(days=3)) and not services.is_period_date(weekly, TODAY + timedelta(days=3))


def test_a_daily_chama_rests_on_sunday():
    """Monday to Saturday only: Saturday's turn ends the week and the next member's turn starts on Monday."""
    monday = date(2026, 10, 5)
    daily = Chama(frequency="DAILY", start_date=monday, periods_per_round=6, grace_days=1)
    days = services.periods_between(daily, None, monday + timedelta(days=14))
    assert all(day.weekday() != 6 for day in days) and len(days) == 13  # two weeks and a Monday, no Sundays
    assert services.round_dates(daily, 1) == [monday + timedelta(days=i) for i in range(6)]
    assert services.round_dates(daily, 2) == [monday + timedelta(days=7 + i) for i in range(6)]  # starts Monday the 12th
    sunday = date(2026, 10, 11)
    assert not services.is_period_date(daily, sunday) and services.period_index(daily, sunday) == 5  # still Saturday's
    assert services.deadline_for(daily, date(2026, 10, 10)) == date(2026, 10, 12)  # Saturday + 1 grace day: Monday
    assert services.period_index(daily, date(2026, 10, 12)) == 6
    for index in range(40):
        assert services.period_index(daily, services.period_date(daily, index)) == index


def test_a_daily_chama_cannot_start_on_a_sunday(on):
    with pytest.raises(ValidationError, match="Sunday is the chama's rest day"):
        services._rules({"frequency": "DAILY", "start_date": date(2026, 10, 11)}, TODAY)
    assert services._rules({"frequency": "WEEKLY", "start_date": date(2026, 10, 11)}, TODAY)["start_date"] == date(2026, 10, 11)


# --- Setting up -------------------------------------------------------------------------------------------------

def test_owner_sets_up_a_chama_from_the_dashboard_which_turns_chama_management_on(on):
    org, owner, client = business()
    state = client.get("/api/v1/chama/setup/").json()
    assert state["enabled"] is False and state["plan_allows"] is True and state["can_turn_on"] is True
    assert client.get("/api/v1/chama/").status_code == 403  # not turned on yet
    made = client.post("/api/v1/chama/setup/", setup_data(), format="json")
    assert made.status_code == 201, made.content
    org.refresh_from_db()
    assert "chama" in org.enabled_modules
    data = made.json()
    assert [(m["full_name"], m["role"], m["turn_position"]) for m in data["members"]] == [
        ("Larry Musau", "TREASURER", 1), ("Mary Achieng", "MEMBER", 2), ("John Kamau", "MEMBER", 3)]
    assert data["current_period"] == str(TODAY) and Decimal(data["money"]["unpaid"]) == Decimal("1500")
    assert [row["member"] for row in data["turns"]] == ["Larry Musau", "Mary Achieng", "John Kamau"]
    listed = client.get("/api/v1/chama/").json()["chamas"]
    assert listed[0]["name"] == "Umoja Chama" and listed[0]["due_count"] == 3 and listed[0]["next_turn"]["member"] == "Larry Musau"


@pytest.mark.parametrize("change, message", [
    ({"members": members("Larry Musau")}, "at least two members"),
    ({"members": [{**m, "role": "MEMBER"} for m in members("Larry Musau", "Mary Achieng")]}, "treasurer"),
    ({"members": [{**m, "id_number": "11112222"} for m in members("Larry Musau", "Mary Achieng")]}, "more than one member"),
    ({"members": [{**m, "role": "TREASURER"} for m in members("Larry Musau", "Mary Achieng")]}, "Only one member can be treasurer"),
    ({"members": [{**members("Larry")[0]}, members("A", "Mary Achieng")[1]]}, "full name"),
    ({"start_date": str(TODAY - timedelta(days=60))}, "within the last month"),
])
def test_setup_explains_what_is_wrong(on, change, message):
    org, owner, client = business()
    response = client.post("/api/v1/chama/setup/", setup_data(**change), format="json")
    assert response.status_code == 400 and message in str(response.content.decode()), response.content
    org.refresh_from_db()
    assert "chama" not in org.enabled_modules  # nothing is turned on when the set-up fails


def test_chama_management_is_a_pro_tool(on):
    basic = SubscriptionPlan.objects.get(code="BASIC")
    org, owner, client = business(plan=basic)
    assert client.get("/api/v1/chama/setup/").json()["plan_allows"] is False
    response = client.post("/api/v1/chama/setup/", setup_data(), format="json")
    assert response.status_code == 403 and "Pro plan" in response.json()["detail"]
    assert "chama" in SubscriptionPlan.objects.get(code="PRO").enabled_modules


def test_registration_sets_up_the_chama_with_the_business(on):
    owner = User.objects.create_user("newowner", password="Safe-pass-1848")
    client = APIClient()
    client.force_login(owner)
    response = client.post("/api/v1/tenancy/create/", {
        "name": "Mama Duka", "business_model": "GOODS", "sector": "duka", "business_size": "SOLO", "plan": "PRO",
        "enabled_modules": ["inventory", "pos", "chama"], "chama": setup_data(name="Wamama Chama")}, format="json")
    assert response.status_code == 201, response.content
    org = Organization.objects.get(pk=response.json()["id"])
    with organization_context(org):
        chama = Chama.objects.get()
        assert chama.name == "Wamama Chama" and chama.members.count() == 3
    bad = client.post("/api/v1/tenancy/create/", {
        "name": "Second", "business_model": "GOODS", "sector": "duka", "enabled_modules": ["inventory", "pos", "chama"],
        "chama": setup_data(members=members("Only One"))}, format="json")
    assert bad.status_code == 400 and not Organization.objects.filter(name="Second").exists()


# --- Who has paid, fines and excuses ------------------------------------------------------------------------------

def test_who_has_paid_and_late_members_are_fined_once(on):
    org, owner, _ = business(modules=["pos", "chama"])
    chama = make(org, owner)
    with organization_context(org):
        larry, mary, john = chama.members.all()
        services.record_payment(chama=chama, member_id=larry.pk, amount="500", paid_on=TODAY, method="CASH", key="p1", user=owner)
        services.record_payment(chama=chama, member_id=mary.pk, amount="200", paid_on=TODAY, method="MPESA", reference="sk1abc", key="p2", user=owner)
    seen, _ = board(org, chama)
    assert seen == {"Larry Musau": (Decimal("500"), "PAID"), "Mary Achieng": (Decimal("200"), "WAITING"), "John Kamau": (Decimal("0"), "WAITING")}
    on(TODAY + timedelta(days=2))  # the last day of grace: nobody is late yet
    assert board(org, chama)[0]["John Kamau"][1] == "WAITING"
    on(TODAY + timedelta(days=3))
    seen, data = board(org, chama)
    assert seen["John Kamau"][1] == "LATE" and seen["Mary Achieng"][1] == "LATE"
    assert sorted((f["member"], Decimal(f["fine_amount"])) for f in data["fines"]) == [("John Kamau", Decimal("50")), ("Mary Achieng", Decimal("50"))]
    board(org, chama)  # looking again never fines twice
    with organization_context(org):
        assert ChamaDue.objects.filter(fine_amount__gt=0).count() == 2
        # A later fine change does not rewrite fines already charged.
        services.update_rules(chama=chama, user=owner, data={"fine_amount": Decimal("100")})
        assert set(ChamaDue.objects.filter(fine_amount__gt=0).values_list("fine_amount", flat=True)) == {Decimal("50")}
    assert Decimal(data["money"]["late"]) == Decimal("800") and Decimal(data["money"]["fines_owed"]) == Decimal("100")


def test_payment_clears_the_oldest_contribution_then_fines_then_pays_ahead(on):
    org, owner, _ = business(modules=["chama"])
    chama = make(org, owner)
    on(TODAY + timedelta(days=8))  # second week: week one is late and fined, week two not yet
    with organization_context(org):
        mary = chama.members.get(full_name="Mary Achieng")
        payment = services.record_payment(chama=chama, member_id=mary.pk, amount="1550", paid_on=None, method="CASH", key="m1", user=owner)
        parts = [(a.due.period_date, a.part, a.amount) for a in payment.allocations.order_by("pk")]
        assert parts == [(TODAY, "CONTRIBUTION", Decimal("500")), (TODAY + timedelta(days=7), "CONTRIBUTION", Decimal("500")),
                         (TODAY, "FINE", Decimal("50")), (TODAY + timedelta(days=14), "CONTRIBUTION", Decimal("500"))]
        with pytest.raises(ValidationError, match="owes less"):
            services.record_payment(chama=chama, member_id=mary.pk, amount="99999", paid_on=None, method="CASH", key="m2", user=owner)
        assert services.record_payment(chama=chama, member_id=mary.pk, amount="1550", paid_on=None, method="CASH", key="m1", user=owner) == payment
    on(TODAY + timedelta(days=14))
    assert board(org, chama)[0]["Mary Achieng"] == (Decimal("500"), "PAID")  # paid ahead last week


def test_a_payment_recorded_after_the_deadline_but_paid_in_time_is_not_fined(on):
    org, owner, _ = business(modules=["chama"])
    chama = make(org, owner)
    on(TODAY + timedelta(days=4))
    board(org, chama)  # the fine is charged: nothing was recorded in time
    with organization_context(org):
        john = chama.members.get(full_name="John Kamau")
        assert ChamaDue.objects.get(member=john, period_date=TODAY).fine_amount == Decimal("50")
        services.record_payment(chama=chama, member_id=john.pk, amount="500", paid_on=TODAY + timedelta(days=1), method="CASH", key="j1", user=owner)
        due = ChamaDue.objects.get(member=john, period_date=TODAY)
        assert due.fine_waived_at is not None and "on time" in due.fine_waive_reason


def test_an_excused_member_pays_by_the_promised_date_or_is_fined(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner)
    next_week = TODAY + timedelta(days=7)
    with organization_context(org):
        mary, john = chama.members.get(full_name="Mary Achieng"), chama.members.get(full_name="John Kamau")
    # Excused in advance for next week's contribution, promising to pay within ten days of it.
    for member in (mary, john):
        response = client.post(f"/api/v1/chama/{chama.pk}/excuses/", {"member": member.pk, "period_date": str(next_week),
                               "pay_by": str(next_week + timedelta(days=10)), "reason": "Waiting for salary"}, format="json")
        assert response.status_code == 201, response.content
    with organization_context(org):
        for member in (mary, john):  # this week's contributions paid
            services.record_payment(chama=chama, member_id=member.pk, amount="500", paid_on=None, method="CASH", key=f"t{member.pk}", user=owner)
    on(next_week + timedelta(days=5))  # past the usual deadline, within the promise
    seen, data = board(org, chama)
    assert seen["Mary Achieng"][1] == "EXCUSED" and seen["Larry Musau"][1] == "LATE"
    assert [e["excuse_reason"] for e in data["excuses"]] == ["Waiting for salary"] * 2
    with organization_context(org):
        services.record_payment(chama=chama, member_id=mary.pk, amount="500", paid_on=None, method="CASH", key="late-but-promised", user=owner)
    on(next_week + timedelta(days=11))  # John broke his promise
    _, data = board(org, chama)
    assert sorted(f["member"] for f in data["fines"] if f["period_date"] == next_week) == ["John Kamau", "Larry Musau"]
    bad = client.post(f"/api/v1/chama/{chama.pk}/excuses/", {"member": mary.pk, "period_date": str(TODAY + timedelta(days=3)),
                      "pay_by": str(TODAY + timedelta(days=30)), "reason": "x"}, format="json")
    assert bad.status_code == 400  # not a contribution date


def test_fines_can_be_waived_with_a_reason_and_payments_reversed(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner)
    on(TODAY + timedelta(days=3))
    _, data = board(org, chama)
    fine = data["fines"][0]
    assert client.post(f"/api/v1/chama/dues/{fine['id']}/waive-fine/", {"reason": ""}, format="json").status_code == 400
    waived = client.post(f"/api/v1/chama/dues/{fine['id']}/waive-fine/", {"reason": "Was in hospital"}, format="json")
    assert waived.status_code == 200 and Decimal(waived.json()["money"]["fines_owed"]) == Decimal("100")
    on(TODAY + timedelta(days=7))
    with organization_context(org):
        larry = chama.members.get(role="TREASURER")
        payment = services.record_payment(chama=chama, member_id=larry.pk, amount="500", paid_on=TODAY + timedelta(days=7), method="CASH", key="w", user=owner)
    on(TODAY + timedelta(days=8))
    # The first payment cleared the late week, not this one. Reversing it brings that debt back.
    undone = client.post(f"/api/v1/chama/payments/{payment.pk}/reverse/", {"reason": "Counted twice"}, format="json")
    assert undone.status_code == 200 and Decimal(undone.json()["money"]["held"]) == 0


# --- Turns and money given out ------------------------------------------------------------------------------------

def test_members_receive_the_money_in_turn_order(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner)
    with organization_context(org):
        larry, mary, john = chama.members.all()
        for member in (larry, mary, john):
            services.record_payment(chama=chama, member_id=member.pk, amount="500", paid_on=None, method="CASH", key=f"r{member.pk}", user=owner)
    # Mary and John swap turns.
    assert client.post(f"/api/v1/chama/{chama.pk}/turns/", {"order": [mary.pk, larry.pk, john.pk]}, format="json").status_code == 200
    too_much = client.post(f"/api/v1/chama/{chama.pk}/payouts/", {"amount": "1600", "method": "CASH", "idempotency_key": "o0"}, format="json")
    assert too_much.status_code == 400 and "holds only 1,500.00" in too_much.content.decode()
    given = client.post(f"/api/v1/chama/{chama.pk}/payouts/", {"amount": "1500", "method": "MPESA", "reference": "SK9", "idempotency_key": "o1"}, format="json")
    assert given.status_code == 201, given.content
    data = given.json()
    assert data["payouts"][0]["member"] == "Mary Achieng" and data["payouts"][0]["round"] == 1
    assert [(t["member"], t["status"]) for t in data["turns"]] == [("Mary Achieng", "GIVEN"), ("Larry Musau", "UPCOMING"),
                                                                  ("John Kamau", "UPCOMING"), ("Mary Achieng", "UPCOMING")]
    assert Decimal(data["money"]["held"]) == 0
    member_rows = {m["full_name"]: m for m in data["members"]}
    assert Decimal(member_rows["Mary Achieng"]["received"]) == Decimal("1500") and member_rows["Larry Musau"]["next_turn"]["round"] == 2
    payout_id = data["payouts"][0]["id"]
    assert client.post(f"/api/v1/chama/payouts/{payout_id}/reverse/", {"reason": "Wrong person"}, format="json").status_code == 200


def test_leadership_moves_and_the_treasurer_is_never_left_empty(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner)
    with organization_context(org):
        larry, mary, john = chama.members.all()
    refused = client.patch(f"/api/v1/chama/{chama.pk}/members/{larry.pk}/", {"role": "MEMBER"}, format="json")
    assert refused.status_code == 400 and "treasurer" in refused.content.decode()
    moved = client.patch(f"/api/v1/chama/{chama.pk}/members/{mary.pk}/", {"role": "TREASURER"}, format="json").json()
    assert {m["full_name"]: m["role"] for m in moved["members"]} == {"Larry Musau": "MEMBER", "Mary Achieng": "TREASURER", "John Kamau": "MEMBER"}
    added = client.post(f"/api/v1/chama/{chama.pk}/members/", {"full_name": "Peter Otieno", "id_number": "30000001", "phone": "0722000111",
                        "role": "SECRETARY"}, format="json")
    assert added.status_code == 201 and Decimal([m for m in added.json()["members"] if m["full_name"] == "Peter Otieno"][0]["unpaid"]) == 500
    left = client.post(f"/api/v1/chama/{chama.pk}/members/{john.pk}/leave/", {"reason": "Moved away"}, format="json").json()
    assert [t["member"] for t in left["turns"]] == ["Larry Musau", "Mary Achieng", "Peter Otieno"]


# --- Kept apart from the shop ---------------------------------------------------------------------------------------

def test_chama_money_never_enters_the_shops_books(on):
    org, owner, client = business(modules=["pos", "inventory", "chama"])
    with organization_context(org):
        before = (CashEntry.objects.count(), JournalEntry.objects.count())
    chama = make(org, owner)
    with organization_context(org):
        for member in chama.members.all():
            services.record_payment(chama=chama, member_id=member.pk, amount="1000", paid_on=None, method="CASH", key=f"s{member.pk}", user=owner)
        services.record_payout(chama=chama, amount="1500", method="CASH", key="s-out", user=owner)
        assert (CashEntry.objects.count(), JournalEntry.objects.count()) == before
    summary = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]
    assert "1500" not in str(summary) and "3000" not in str(summary)


def test_only_the_owner_and_administrators_see_a_chama_by_default(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner)
    for role in ("MANAGER", "READ_ONLY", "CASHIER"):
        user = User.objects.create_user(f"staff-{role}", password="Safe-pass-1848")
        Membership.objects.create(user=user, organization=org, role=role)
        staff = APIClient()
        staff.force_login(user)
        assert staff.get(f"/api/v1/chama/{chama.pk}/").status_code == 403, role
        assert staff.post("/api/v1/chama/setup/", setup_data(), format="json").status_code == 403, role
    other, other_owner, other_client = business(modules=["chama"])
    assert other_client.get(f"/api/v1/chama/{chama.pk}/").status_code == 404  # another business's chama does not exist for them
    with organization_context(org):
        assert ChamaMember.objects.count() == 3


def test_members_give_daily_for_a_week_and_agree_who_receives_next(on):
    """100 every day but Sunday; after a week (six contributions, Monday to Saturday) one member receives, and the members agree
    who that is each turn. TODAY is a Tuesday, so the first turn runs Tuesday to the next Monday, skipping Sunday."""
    org, owner, client = business(modules=["chama"])
    made = client.post("/api/v1/chama/setup/", setup_data(contribution_amount="100", frequency="DAILY", grace_days=0, fine_amount="0",
                       periods_per_round=6, turn_choice="AGREED", first_receiver=2), format="json")
    assert made.status_code == 201, made.content
    data = made.json()
    larry, mary, john = (m["id"] for m in data["members"])
    assert data["next_receiver"]["full_name"] == "John Kamau"  # agreed when the chama was set up
    assert [(t["round"], t["date"], t["member"]) for t in data["turns"]] == [
        (1, str(TODAY + timedelta(days=6)), "John Kamau"), (2, str(TODAY + timedelta(days=13)), ""), (3, str(TODAY + timedelta(days=20)), "")]
    with organization_context(org):
        chama = Chama.objects.get(pk=data["id"])
        for member in (larry, mary, john):  # each pays the whole week
            services.record_payment(chama=chama, member_id=member, amount="600", paid_on=None, method="CASH", key=f"week-{member}", user=owner)
    on(TODAY + timedelta(days=6))
    turn = client.get(f"/api/v1/chama/{chama.pk}/").json()["turns"][0]
    assert (turn["status"], Decimal(turn["collected"]), Decimal(turn["expected"])) == ("DUE", Decimal("1800"), Decimal("1800"))
    given = client.post(f"/api/v1/chama/{chama.pk}/payouts/", {"amount": "1800", "method": "CASH", "idempotency_key": "w1"}, format="json").json()
    assert given["payouts"][0]["member"] == "John Kamau" and given["next_receiver"] is None
    assert [m["full_name"] for m in given["still_to_receive"]] == ["Larry Musau", "Mary Achieng"]
    # Next week nobody has been agreed yet, so the money cannot go out until the members choose.
    on(TODAY + timedelta(days=13))
    refused = client.post(f"/api/v1/chama/{chama.pk}/payouts/", {"amount": "10", "method": "CASH", "idempotency_key": "w2"}, format="json")
    assert refused.status_code == 400 and "not agreed" in refused.content.decode()
    again = client.post(f"/api/v1/chama/{chama.pk}/next-receiver/", {"member": john, "note": "Again"}, format="json")
    assert again.status_code == 400 and "already received" in again.content.decode()
    agreed = client.post(f"/api/v1/chama/{chama.pk}/next-receiver/", {"member": mary, "note": "Agreed at Sunday's meeting"}, format="json").json()
    assert agreed["next_receiver"]["note"] == "Agreed at Sunday's meeting" and agreed["turns"][1]["member"] == "Mary Achieng"
    assert agreed["turns"][1]["agreed"] is True
    cleared = client.post(f"/api/v1/chama/{chama.pk}/next-receiver/", {"member": None}, format="json").json()
    assert cleared["next_receiver"] is None


def test_an_agreed_receiver_jumps_the_listed_order(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner)
    with organization_context(org):
        john = chama.members.get(full_name="John Kamau")
    data = client.post(f"/api/v1/chama/{chama.pk}/next-receiver/", {"member": john.pk, "note": "Hospital bill"}, format="json").json()
    assert [t["member"] for t in data["turns"]] == ["John Kamau", "Larry Musau", "Mary Achieng"]
    assert data["turn_choice"] == "ORDER"


# --- Adding and removing members ----------------------------------------------------------------------------------

def test_members_are_added_removed_by_mistake_leave_and_rejoin(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner)
    url = f"/api/v1/chama/{chama.pk}/members/"
    added = client.post(url, {"full_name": "Peter Otieno", "id_number": "30000001", "phone": "0712345699"}, format="json")
    assert added.status_code == 201, added.content
    peter = next(m for m in added.json()["members"] if m["full_name"] == "Peter Otieno")
    assert peter["active"] and not peter["has_money_history"]
    # Added by mistake, with no money paid: deleted completely, with what he was said to owe.
    assert client.post(f"{url}{peter['id']}/remove/", {"reason": ""}, format="json").status_code == 400
    removed = client.post(f"{url}{peter['id']}/remove/", {"reason": "Wrong chama"}, format="json").json()
    assert "Peter Otieno" not in [m["full_name"] for m in removed["members"]]
    with organization_context(org):
        assert not ChamaMember.objects.filter(id_number="30000001").exists()
        mary = ChamaMember.objects.get(full_name="Mary Achieng")
        services.record_payment(chama=chama, member_id=mary.pk, amount="500", paid_on=TODAY, method="CASH", key="m1", user=owner)
    # Someone who paid in cannot be deleted: she leaves, and her record stays.
    refused = client.post(f"{url}{mary.pk}/remove/", {"reason": "Mistake"}, format="json")
    assert refused.status_code == 400 and "Leaves the chama" in str(refused.json())
    left = client.post(f"{url}{mary.pk}/leave/", {"reason": "Moved away"}, format="json").json()
    gone = next(m for m in left["members"] if m["full_name"] == "Mary Achieng")
    assert not gone["active"] and gone["has_money_history"]
    # She comes back: owes again from today, takes the last turn.
    on(TODAY + timedelta(days=14))
    back = client.post(f"{url}{mary.pk}/rejoin/", {}, format="json").json()
    mary_now = next(m for m in back["members"] if m["full_name"] == "Mary Achieng")
    assert mary_now["active"] and mary_now["turn_position"] == max(m["turn_position"] for m in back["members"])
    with organization_context(org):
        owed = list(ChamaDue.objects.filter(member=mary).values_list("period_date", flat=True))
    assert TODAY + timedelta(days=7) not in owed and TODAY + timedelta(days=14) in owed  # nothing while away
    # The treasurer cannot be deleted, and a chama keeps at least two members.
    with organization_context(org):
        larry = ChamaMember.objects.get(full_name="Larry Musau")
        john = ChamaMember.objects.get(full_name="John Kamau")
    assert "treasurer" in str(client.post(f"{url}{larry.pk}/remove/", {"reason": "x"}, format="json").json())
    client.post(f"{url}{mary.pk}/leave/", {"reason": "Moved again"}, format="json")
    assert "at least two members" in str(client.post(f"{url}{john.pk}/remove/", {"reason": "x"}, format="json").json())


def test_a_new_contribution_amount_applies_from_the_next_contribution(on):
    org, owner, client = business(modules=["chama"])
    chama = make(org, owner, frequency="DAILY", periods_per_round=7)
    board(org, chama)  # today's contribution is owed at the old amount
    saved = client.patch(f"/api/v1/chama/{chama.pk}/", {"contribution_amount": "200"}, format="json")
    assert saved.status_code == 200, saved.content
    on(TODAY + timedelta(days=1))
    seen, data = board(org, chama)
    with organization_context(org):
        amounts = dict(ChamaDue.objects.filter(member__full_name="Mary Achieng").values_list("period_date", "amount"))
    assert amounts[TODAY] == Decimal("500") and amounts[TODAY + timedelta(days=1)] == Decimal("200")
    assert Decimal(data["contribution_amount"]) == Decimal("200")
