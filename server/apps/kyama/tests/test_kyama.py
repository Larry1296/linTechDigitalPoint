"""Kyama management: setting up, who has paid, fines, excuses, turns, and that the shop's books are never touched."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounting.models import CashEntry, JournalEntry
from apps.core.models import Store
from apps.kyama import services
from apps.kyama.models import Kyama, KyamaDue, KyamaMember
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
    return {"name": "Umoja Kyama", "contribution_amount": "500", "frequency": "WEEKLY", "start_date": str(TODAY), "grace_days": 2,
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
    from apps.kyama.api import KyamaInput
    form = KyamaInput(data=setup_data(**overrides))
    form.is_valid(raise_exception=True)
    with organization_context(org):
        return services.create_kyama(user=owner, data=form.validated_data)


def board(org, kyama):
    """{member name: (paid, status, fine)} for the current period, as the treasurer sees it."""
    from apps.kyama.api import kyama_detail
    with organization_context(org):
        data = kyama_detail(services.sync(kyama), timezone.localdate())
    return {m["full_name"]: (m["this_period"]["paid"], m["this_period"]["status"]) for m in data["members"] if m["this_period"]}, data


# --- Schedule ---------------------------------------------------------------------------------------------------

def test_contribution_dates_follow_the_chosen_frequency():
    monthly = Kyama(frequency="MONTHLY", start_date=date(2026, 1, 31))
    assert [services.period_date(monthly, i) for i in range(4)] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    assert services.period_index(monthly, date(2026, 3, 30)) == 1 and services.period_index(monthly, date(2026, 3, 31)) == 2
    assert services.period_index(monthly, date(2026, 1, 30)) == -1
    weekly = Kyama(frequency="WEEKLY", start_date=TODAY)
    assert services.periods_between(weekly, None, TODAY + timedelta(days=15)) == [TODAY, TODAY + timedelta(days=7), TODAY + timedelta(days=14)]
    daily = Kyama(frequency="DAILY", start_date=TODAY)
    assert services.is_period_date(daily, TODAY + timedelta(days=3)) and not services.is_period_date(weekly, TODAY + timedelta(days=3))


# --- Setting up -------------------------------------------------------------------------------------------------

def test_owner_sets_up_a_kyama_from_the_dashboard_which_turns_kyama_management_on(on):
    org, owner, client = business()
    state = client.get("/api/v1/kyama/setup/").json()
    assert state["enabled"] is False and state["plan_allows"] is True and state["can_turn_on"] is True
    assert client.get("/api/v1/kyama/").status_code == 403  # not turned on yet
    made = client.post("/api/v1/kyama/setup/", setup_data(), format="json")
    assert made.status_code == 201, made.content
    org.refresh_from_db()
    assert "kyama" in org.enabled_modules
    data = made.json()
    assert [(m["full_name"], m["role"], m["turn_position"]) for m in data["members"]] == [
        ("Larry Musau", "TREASURER", 1), ("Mary Achieng", "MEMBER", 2), ("John Kamau", "MEMBER", 3)]
    assert data["current_period"] == str(TODAY) and Decimal(data["money"]["unpaid"]) == Decimal("1500")
    assert [row["member"] for row in data["turns"]] == ["Larry Musau", "Mary Achieng", "John Kamau"]
    listed = client.get("/api/v1/kyama/").json()["kyamas"]
    assert listed[0]["name"] == "Umoja Kyama" and listed[0]["due_count"] == 3 and listed[0]["next_turn"]["member"] == "Larry Musau"


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
    response = client.post("/api/v1/kyama/setup/", setup_data(**change), format="json")
    assert response.status_code == 400 and message in str(response.content.decode()), response.content
    org.refresh_from_db()
    assert "kyama" not in org.enabled_modules  # nothing is turned on when the set-up fails


def test_kyama_management_is_a_pro_tool(on):
    basic = SubscriptionPlan.objects.get(code="BASIC")
    org, owner, client = business(plan=basic)
    assert client.get("/api/v1/kyama/setup/").json()["plan_allows"] is False
    response = client.post("/api/v1/kyama/setup/", setup_data(), format="json")
    assert response.status_code == 403 and "Pro plan" in response.json()["detail"]
    assert "kyama" in SubscriptionPlan.objects.get(code="PRO").enabled_modules


def test_registration_sets_up_the_kyama_with_the_business(on):
    owner = User.objects.create_user("newowner", password="Safe-pass-1848")
    client = APIClient()
    client.force_login(owner)
    response = client.post("/api/v1/tenancy/create/", {
        "name": "Mama Duka", "business_model": "GOODS", "sector": "duka", "business_size": "SOLO", "plan": "PRO",
        "enabled_modules": ["inventory", "pos", "kyama"], "kyama": setup_data(name="Wamama Chama")}, format="json")
    assert response.status_code == 201, response.content
    org = Organization.objects.get(pk=response.json()["id"])
    with organization_context(org):
        kyama = Kyama.objects.get()
        assert kyama.name == "Wamama Chama" and kyama.members.count() == 3
    bad = client.post("/api/v1/tenancy/create/", {
        "name": "Second", "business_model": "GOODS", "sector": "duka", "enabled_modules": ["inventory", "pos", "kyama"],
        "kyama": setup_data(members=members("Only One"))}, format="json")
    assert bad.status_code == 400 and not Organization.objects.filter(name="Second").exists()


# --- Who has paid, fines and excuses ------------------------------------------------------------------------------

def test_who_has_paid_and_late_members_are_fined_once(on):
    org, owner, _ = business(modules=["pos", "kyama"])
    kyama = make(org, owner)
    with organization_context(org):
        larry, mary, john = kyama.members.all()
        services.record_payment(kyama=kyama, member_id=larry.pk, amount="500", paid_on=TODAY, method="CASH", key="p1", user=owner)
        services.record_payment(kyama=kyama, member_id=mary.pk, amount="200", paid_on=TODAY, method="MPESA", reference="sk1abc", key="p2", user=owner)
    seen, _ = board(org, kyama)
    assert seen == {"Larry Musau": (Decimal("500"), "PAID"), "Mary Achieng": (Decimal("200"), "WAITING"), "John Kamau": (Decimal("0"), "WAITING")}
    on(TODAY + timedelta(days=2))  # the last day of grace: nobody is late yet
    assert board(org, kyama)[0]["John Kamau"][1] == "WAITING"
    on(TODAY + timedelta(days=3))
    seen, data = board(org, kyama)
    assert seen["John Kamau"][1] == "LATE" and seen["Mary Achieng"][1] == "LATE"
    assert sorted((f["member"], Decimal(f["fine_amount"])) for f in data["fines"]) == [("John Kamau", Decimal("50")), ("Mary Achieng", Decimal("50"))]
    board(org, kyama)  # looking again never fines twice
    with organization_context(org):
        assert KyamaDue.objects.filter(fine_amount__gt=0).count() == 2
        # A later fine change does not rewrite fines already charged.
        services.update_rules(kyama=kyama, user=owner, data={"fine_amount": Decimal("100")})
        assert set(KyamaDue.objects.filter(fine_amount__gt=0).values_list("fine_amount", flat=True)) == {Decimal("50")}
    assert Decimal(data["money"]["late"]) == Decimal("800") and Decimal(data["money"]["fines_owed"]) == Decimal("100")


def test_payment_clears_the_oldest_contribution_then_fines_then_pays_ahead(on):
    org, owner, _ = business(modules=["kyama"])
    kyama = make(org, owner)
    on(TODAY + timedelta(days=8))  # second week: week one is late and fined, week two not yet
    with organization_context(org):
        mary = kyama.members.get(full_name="Mary Achieng")
        payment = services.record_payment(kyama=kyama, member_id=mary.pk, amount="1550", paid_on=None, method="CASH", key="m1", user=owner)
        parts = [(a.due.period_date, a.part, a.amount) for a in payment.allocations.order_by("pk")]
        assert parts == [(TODAY, "CONTRIBUTION", Decimal("500")), (TODAY + timedelta(days=7), "CONTRIBUTION", Decimal("500")),
                         (TODAY, "FINE", Decimal("50")), (TODAY + timedelta(days=14), "CONTRIBUTION", Decimal("500"))]
        with pytest.raises(ValidationError, match="owes less"):
            services.record_payment(kyama=kyama, member_id=mary.pk, amount="99999", paid_on=None, method="CASH", key="m2", user=owner)
        assert services.record_payment(kyama=kyama, member_id=mary.pk, amount="1550", paid_on=None, method="CASH", key="m1", user=owner) == payment
    on(TODAY + timedelta(days=14))
    assert board(org, kyama)[0]["Mary Achieng"] == (Decimal("500"), "PAID")  # paid ahead last week


def test_a_payment_recorded_after_the_deadline_but_paid_in_time_is_not_fined(on):
    org, owner, _ = business(modules=["kyama"])
    kyama = make(org, owner)
    on(TODAY + timedelta(days=4))
    board(org, kyama)  # the fine is charged: nothing was recorded in time
    with organization_context(org):
        john = kyama.members.get(full_name="John Kamau")
        assert KyamaDue.objects.get(member=john, period_date=TODAY).fine_amount == Decimal("50")
        services.record_payment(kyama=kyama, member_id=john.pk, amount="500", paid_on=TODAY + timedelta(days=1), method="CASH", key="j1", user=owner)
        due = KyamaDue.objects.get(member=john, period_date=TODAY)
        assert due.fine_waived_at is not None and "on time" in due.fine_waive_reason


def test_an_excused_member_pays_by_the_promised_date_or_is_fined(on):
    org, owner, client = business(modules=["kyama"])
    kyama = make(org, owner)
    next_week = TODAY + timedelta(days=7)
    with organization_context(org):
        mary, john = kyama.members.get(full_name="Mary Achieng"), kyama.members.get(full_name="John Kamau")
    # Excused in advance for next week's contribution, promising to pay within ten days of it.
    for member in (mary, john):
        response = client.post(f"/api/v1/kyama/{kyama.pk}/excuses/", {"member": member.pk, "period_date": str(next_week),
                               "pay_by": str(next_week + timedelta(days=10)), "reason": "Waiting for salary"}, format="json")
        assert response.status_code == 201, response.content
    with organization_context(org):
        for member in (mary, john):  # this week's contributions paid
            services.record_payment(kyama=kyama, member_id=member.pk, amount="500", paid_on=None, method="CASH", key=f"t{member.pk}", user=owner)
    on(next_week + timedelta(days=5))  # past the usual deadline, within the promise
    seen, data = board(org, kyama)
    assert seen["Mary Achieng"][1] == "EXCUSED" and seen["Larry Musau"][1] == "LATE"
    assert [e["excuse_reason"] for e in data["excuses"]] == ["Waiting for salary"] * 2
    with organization_context(org):
        services.record_payment(kyama=kyama, member_id=mary.pk, amount="500", paid_on=None, method="CASH", key="late-but-promised", user=owner)
    on(next_week + timedelta(days=11))  # John broke his promise
    _, data = board(org, kyama)
    assert sorted(f["member"] for f in data["fines"] if f["period_date"] == next_week) == ["John Kamau", "Larry Musau"]
    bad = client.post(f"/api/v1/kyama/{kyama.pk}/excuses/", {"member": mary.pk, "period_date": str(TODAY + timedelta(days=3)),
                      "pay_by": str(TODAY + timedelta(days=30)), "reason": "x"}, format="json")
    assert bad.status_code == 400  # not a contribution date


def test_fines_can_be_waived_with_a_reason_and_payments_reversed(on):
    org, owner, client = business(modules=["kyama"])
    kyama = make(org, owner)
    on(TODAY + timedelta(days=3))
    _, data = board(org, kyama)
    fine = data["fines"][0]
    assert client.post(f"/api/v1/kyama/dues/{fine['id']}/waive-fine/", {"reason": ""}, format="json").status_code == 400
    waived = client.post(f"/api/v1/kyama/dues/{fine['id']}/waive-fine/", {"reason": "Was in hospital"}, format="json")
    assert waived.status_code == 200 and Decimal(waived.json()["money"]["fines_owed"]) == Decimal("100")
    on(TODAY + timedelta(days=7))
    with organization_context(org):
        larry = kyama.members.get(role="TREASURER")
        payment = services.record_payment(kyama=kyama, member_id=larry.pk, amount="500", paid_on=TODAY + timedelta(days=7), method="CASH", key="w", user=owner)
    on(TODAY + timedelta(days=8))
    # The first payment cleared the late week, not this one. Reversing it brings that debt back.
    undone = client.post(f"/api/v1/kyama/payments/{payment.pk}/reverse/", {"reason": "Counted twice"}, format="json")
    assert undone.status_code == 200 and Decimal(undone.json()["money"]["held"]) == 0


# --- Turns and money given out ------------------------------------------------------------------------------------

def test_members_receive_the_money_in_turn_order(on):
    org, owner, client = business(modules=["kyama"])
    kyama = make(org, owner)
    with organization_context(org):
        larry, mary, john = kyama.members.all()
        for member in (larry, mary, john):
            services.record_payment(kyama=kyama, member_id=member.pk, amount="500", paid_on=None, method="CASH", key=f"r{member.pk}", user=owner)
    # Mary and John swap turns.
    assert client.post(f"/api/v1/kyama/{kyama.pk}/turns/", {"order": [mary.pk, larry.pk, john.pk]}, format="json").status_code == 200
    too_much = client.post(f"/api/v1/kyama/{kyama.pk}/payouts/", {"amount": "1600", "method": "CASH", "idempotency_key": "o0"}, format="json")
    assert too_much.status_code == 400 and "holds only 1,500.00" in too_much.content.decode()
    given = client.post(f"/api/v1/kyama/{kyama.pk}/payouts/", {"amount": "1500", "method": "MPESA", "reference": "SK9", "idempotency_key": "o1"}, format="json")
    assert given.status_code == 201, given.content
    data = given.json()
    assert data["payouts"][0]["member"] == "Mary Achieng" and data["payouts"][0]["round"] == 1
    assert [(t["member"], t["status"]) for t in data["turns"]] == [("Mary Achieng", "GIVEN"), ("Larry Musau", "UPCOMING"),
                                                                  ("John Kamau", "UPCOMING"), ("Mary Achieng", "UPCOMING")]
    assert Decimal(data["money"]["held"]) == 0
    member_rows = {m["full_name"]: m for m in data["members"]}
    assert Decimal(member_rows["Mary Achieng"]["received"]) == Decimal("1500") and member_rows["Larry Musau"]["next_turn"]["round"] == 2
    payout_id = data["payouts"][0]["id"]
    assert client.post(f"/api/v1/kyama/payouts/{payout_id}/reverse/", {"reason": "Wrong person"}, format="json").status_code == 200


def test_leadership_moves_and_the_treasurer_is_never_left_empty(on):
    org, owner, client = business(modules=["kyama"])
    kyama = make(org, owner)
    with organization_context(org):
        larry, mary, john = kyama.members.all()
    refused = client.patch(f"/api/v1/kyama/{kyama.pk}/members/{larry.pk}/", {"role": "MEMBER"}, format="json")
    assert refused.status_code == 400 and "treasurer" in refused.content.decode()
    moved = client.patch(f"/api/v1/kyama/{kyama.pk}/members/{mary.pk}/", {"role": "TREASURER"}, format="json").json()
    assert {m["full_name"]: m["role"] for m in moved["members"]} == {"Larry Musau": "MEMBER", "Mary Achieng": "TREASURER", "John Kamau": "MEMBER"}
    added = client.post(f"/api/v1/kyama/{kyama.pk}/members/", {"full_name": "Peter Otieno", "id_number": "30000001", "phone": "0722000111",
                        "role": "SECRETARY"}, format="json")
    assert added.status_code == 201 and Decimal([m for m in added.json()["members"] if m["full_name"] == "Peter Otieno"][0]["unpaid"]) == 500
    left = client.post(f"/api/v1/kyama/{kyama.pk}/members/{john.pk}/leave/", {"reason": "Moved away"}, format="json").json()
    assert [t["member"] for t in left["turns"]] == ["Larry Musau", "Mary Achieng", "Peter Otieno"]


# --- Kept apart from the shop ---------------------------------------------------------------------------------------

def test_kyama_money_never_enters_the_shops_books(on):
    org, owner, client = business(modules=["pos", "inventory", "kyama"])
    with organization_context(org):
        before = (CashEntry.objects.count(), JournalEntry.objects.count())
    kyama = make(org, owner)
    with organization_context(org):
        for member in kyama.members.all():
            services.record_payment(kyama=kyama, member_id=member.pk, amount="1000", paid_on=None, method="CASH", key=f"s{member.pk}", user=owner)
        services.record_payout(kyama=kyama, amount="1500", method="CASH", key="s-out", user=owner)
        assert (CashEntry.objects.count(), JournalEntry.objects.count()) == before
    summary = client.get("/api/v1/inventory/dashboard/").json()["owner_summary"]
    assert "1500" not in str(summary) and "3000" not in str(summary)


def test_only_the_owner_and_administrators_see_a_kyama_by_default(on):
    org, owner, client = business(modules=["kyama"])
    kyama = make(org, owner)
    for role in ("MANAGER", "READ_ONLY", "CASHIER"):
        user = User.objects.create_user(f"staff-{role}", password="Safe-pass-1848")
        Membership.objects.create(user=user, organization=org, role=role)
        staff = APIClient()
        staff.force_login(user)
        assert staff.get(f"/api/v1/kyama/{kyama.pk}/").status_code == 403, role
        assert staff.post("/api/v1/kyama/setup/", setup_data(), format="json").status_code == 403, role
    other, other_owner, other_client = business(modules=["kyama"])
    assert other_client.get(f"/api/v1/kyama/{kyama.pk}/").status_code == 404  # another business's kyama does not exist for them
    with organization_context(org):
        assert KyamaMember.objects.count() == 3
