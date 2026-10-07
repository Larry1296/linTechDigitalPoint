"""Safaricom's monthly commission: counted in the month it was earned, paid through the shift or outside the agency, never faked."""
from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def agency():
    owner = User.objects.create_user("agent-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Agent shop", slug="agent", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        from apps.mpesa.models import MpesaOutlet
        store = Store.objects.create(name="Main")
        outlet = MpesaOutlet.objects.create(store=store, display_name="Agent till")
    client = APIClient()
    client.force_login(owner)
    today = timezone.localdate()
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    return client, org, owner, outlet, today, last_month


def _record(client, outlet, period, amount, reference, settlement, key=None, **extra):
    return client.post("/api/v1/mpesa/commission/", {"outlet": outlet.pk, "period": str(period), "amount": amount, "reference": reference,
                       "settlement_method": settlement, "idempotency_key": key or reference, **extra}, format="json")


def _books(org, start=None, end=None):
    with organization_context(org):
        from apps.accounting import statements
        return statements.balances(start, end), statements.profit_and_loss(start, end), {r["key"]: r for r in statements.reconciliation()}


def _month_end(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def test_last_months_commission_paid_now_counts_in_last_month_and_is_owed_until_paid(agency):
    client, org, _, outlet, today, last_month = agency
    made = _record(client, outlet, last_month, "4200", "sjq1comm01", "MPESA")
    assert made.status_code == 201, made.content
    row = made.json()
    assert (row["reference"], row["earned_on"], row["paid_on"], row["month"]) == ("SJQ1COMM01", str(_month_end(last_month)), str(today), last_month.strftime("%B %Y"))
    accounts, last_pl, _ = _books(org, last_month, _month_end(last_month))
    assert last_pl["revenue"] == D("4200") and next(u for u in last_pl["units"] if u["key"] == "mpesa")["revenue"] == D("4200")
    _, this_pl, _ = _books(org, today.replace(day=1), today)
    assert this_pl["revenue"] == 0  # not counted twice, and not in the month it happened to be paid
    owed = _books(org, None, _month_end(last_month))[0]
    assert owed["1160"]["balance"] == D("4200")  # at the end of last month Safaricom owed it
    assert accounts["1160"]["balance"] == D("4200")
    now = _books(org)[0]
    assert now["1160"]["balance"] == 0 and now["1020"]["balance"] == D("4200")  # paid now: nothing owed, the money is in M-Pesa
    # The same click again records nothing new; the same reference twice is refused.
    assert _record(client, outlet, last_month, "4200", "SJQ1COMM01", "MPESA", key="sjq1comm01").status_code == 201
    again = _record(client, outlet, last_month, "4200", "SJQ1COMM01", "MPESA", key="other-key")
    assert again.status_code == 400 and "already recorded" in str(again.json())
    listing = client.get("/api/v1/mpesa/commission/").json()
    assert len(listing["entries"]) == 1
    month = next(m for m in listing["months"] if m["month"] == str(last_month))
    assert (D(str(month["commission"])), D(str(month["profit"]))) == (D("4200"), D("4200"))


def test_commission_into_the_float_goes_through_the_open_shift_and_can_be_undone(agency):
    client, org, owner, outlet, today, last_month = agency
    refused = _record(client, outlet, last_month, "3000", "SJQ2COMM02", "AGENCY_FLOAT")
    assert refused.status_code == 400 and "Open Agent till's shift first" in str(refused.json())
    with organization_context(org):
        from apps.mpesa.services import open_session, session_balances
        session = open_session(outlet=outlet, operator=owner, opening_cash="10000", opening_float="20000")
    made = _record(client, outlet, last_month, "3000", "SJQ2COMM02", "AGENCY_FLOAT")
    assert made.status_code == 201, made.content
    with organization_context(org):
        assert session_balances(session) == (D("10000.00"), D("23000.00"))  # the float really holds it now
        from apps.mpesa.models import MpesaTransaction
        moved = MpesaTransaction.objects.get(transaction_type="COMMISSION")
    accounts, _, checks = _books(org)
    assert accounts["4010"]["balance"] == D("-3000") and accounts["1160"]["balance"] == 0
    assert checks["agency_float"]["reconciled"]
    # The desk cannot reverse or fake it on its own.
    assert client.post("/api/v1/mpesa/transactions/", {"session": session.pk, "transaction_type": "COMMISSION", "amount": "1",
                       "idempotency_key": "sneak"}, format="json").status_code == 400
    assert client.post(f"/api/v1/mpesa/commission/{made.json()['id']}/undo/", {"reason": ""}, format="json").status_code == 400
    assert client.post(f"/api/v1/mpesa/transactions/{moved.pk}/reverse/", {"reason": "", "idempotency_key": "r1"}, format="json").status_code == 400
    # Reverse on the desk undoes the whole commission: the float and its income both come back out.
    reversed_ = client.post(f"/api/v1/mpesa/transactions/{moved.pk}/reverse/", {"reason": "Wrong month", "idempotency_key": "r1"}, format="json")
    assert reversed_.status_code == 201 and reversed_.json()["reversal_of"] == moved.pk
    undone = client.get(f"/api/v1/mpesa/commission/{made.json()['id']}/")
    assert undone.json()["reversed_at"] and undone.json()["reverse_reason"] == "Wrong month"
    with organization_context(org):
        assert session_balances(session) == (D("10000.00"), D("20000.00"))
    accounts, pl, checks = _books(org)
    assert accounts["4010"]["balance"] == 0 and accounts["1160"]["balance"] == 0 and pl["revenue"] == 0
    assert checks["agency_float"]["reconciled"]


def test_commission_paid_outside_the_agency_is_undone_through_the_cash_book_too(agency):
    client, org, *_ = agency
    _, _, outlet, today, last_month = agency[1:]
    made = _record(client, outlet, last_month, "900", "SJQ3COMM03", "BANK").json()
    undone = client.post(f"/api/v1/mpesa/commission/{made['id']}/undo/", {"reason": "Entered twice"}, format="json").json()
    assert undone["reversed_at"] and undone["reverse_reason"] == "Entered twice"
    accounts, pl, _ = _books(org)
    assert accounts["4010"]["balance"] == 0 and accounts["1160"]["balance"] == 0 and accounts["1010"]["balance"] == 0 and pl["revenue"] == 0


def test_when_last_months_books_are_closed_it_counts_on_the_day_paid_and_says_so(agency):
    client, org, _, outlet, today, last_month = agency
    with organization_context(org):
        from apps.accounting.models import FinancialPeriod
        FinancialPeriod.objects.create(start=last_month, end=_month_end(last_month), closed=True)
    row = _record(client, outlet, last_month, "1500", "SJQ4COMM04", "CASH").json()
    assert row["earned_on"] == str(today) and "books were closed" in row["notes"]
    _, pl, _ = _books(org, today.replace(day=1), today)
    assert pl["revenue"] == D("1500")


def test_impossible_commission_is_refused(agency):
    client, _, _, outlet, today, last_month = agency
    next_month = _month_end(today) + timedelta(days=1)
    cases = [(next_month, {}, "has not started"), (last_month, {"paid_on": str(today + timedelta(days=1))}, "future"),
             (today.replace(day=1), {"paid_on": str(last_month)}, "before the month"), (last_month, {"settlement_method": "SAFARICOM"}, "Choose where")]
    for index, (period, extra, message) in enumerate(cases):
        body = {"settlement_method": "MPESA", **extra}
        response = _record(client, outlet, period, "100", f"SJQ5BAD{index}", body.pop("settlement_method"), **body)
        assert response.status_code == 400 and message in str(response.json()), (message, response.json())


def test_commission_needs_no_mpesa_code(agency):
    # Safaricom pays commission without giving a code, so it records with none, more than once.
    client, org, _, outlet, today, last_month = agency
    for key in ["first", "second"]:
        made = client.post("/api/v1/mpesa/commission/", {"outlet": outlet.pk, "period": str(last_month), "amount": "500",
                           "settlement_method": "BANK", "idempotency_key": key}, format="json")
        assert made.status_code == 201, made.content
        assert made.json()["reference"] == ""
    assert _books(org)[0]["4010"]["balance"] == D("-1000")


def test_reminds_for_last_month_and_agency_profit_takes_off_its_running_costs(agency):
    client, org, owner, outlet, today, last_month = agency
    assert client.get("/api/v1/mpesa/commission/").json()["due_month"] is None  # the agency did not work last month
    with organization_context(org):
        from apps.accounting.models import ExpenseCategory
        from apps.accounting.services import record_expense
        from apps.mpesa.models import MpesaSession
        from apps.mpesa.services import open_session
        session = open_session(outlet=outlet, operator=owner, opening_cash="1000", opening_float="1000")
        MpesaSession.objects.filter(pk=session.pk).update(opened_at=timezone.now() - timedelta(days=40))
        record_expense(user=owner, category=ExpenseCategory.objects.create(name="Agent rent"), unit="MPESA", method="CASH", amount="1000",
                       description="Kiosk rent", key="rent", incurred_on=last_month)
    listing = client.get("/api/v1/mpesa/commission/").json()
    assert listing["due_month"] == str(last_month) and listing["due_label"] == last_month.strftime("%B %Y")
    _record(client, outlet, last_month, "3500", "SJQ6COMM06", "MPESA")
    listing = client.get("/api/v1/mpesa/commission/").json()
    assert listing["due_month"] is None
    month = next(m for m in listing["months"] if m["month"] == str(last_month))
    assert (D(str(month["commission"])), D(str(month["expenses"])), D(str(month["profit"]))) == (D("3500"), D("1000"), D("2500"))
    _, pl, _ = _books(org, last_month, _month_end(last_month))
    assert pl["revenue"] == D("3500")


@pytest.mark.parametrize("settlement", ["AGENCY_FLOAT", "MPESA"])
def test_undoing_last_months_commission_takes_it_out_of_last_month_not_today(agency, settlement):
    # Undoing 1020 earned last month and paid today must not show today's sales as 1020 lower (e.g. 780 - 1020 = -240).
    client, org, owner, outlet, today, last_month = agency
    if settlement == "AGENCY_FLOAT":
        with organization_context(org):
            from apps.mpesa.services import open_session
            open_session(outlet=outlet, operator=owner, opening_cash="1000", opening_float="1000")
    made = _record(client, outlet, last_month, "1020", "SJQ7COMM07", settlement)
    assert made.status_code == 201, made.content
    assert client.post(f"/api/v1/mpesa/commission/{made.json()['id']}/undo/", {"reason": "Entered by mistake"}, format="json").status_code == 200
    _, last_pl, _ = _books(org, last_month, _month_end(last_month))
    _, this_pl, _ = _books(org, today.replace(day=1), today)
    assert (last_pl["revenue"], this_pl["revenue"]) == (0, 0)
    assert _books(org)[0]["1160"]["balance"] == 0


def test_commission_undone_on_the_wrong_day_before_the_fix_is_repaired(agency):
    # Records left by the old undo: last month's 1020 taken out today, so today's sales were 1020 too low.
    from io import StringIO
    from django.core.management import call_command
    client, org, owner, outlet, today, last_month = agency
    entry = _record(client, outlet, last_month, "1020", "SJQ8COMM08", "MPESA").json()
    with organization_context(org):
        from apps.accounting.ledger import reverse_journal
        from apps.accounting.models import JournalEntry
        for key, undo_key in [("commission", "commission-reversal"), ("commission-earned", "commission-earned-reversal")]:
            journal = JournalEntry.objects.get(source_key=f"{key}:{entry['id']}")
            reverse_journal(journal, user=owner, reason="old undo", key=f"{undo_key}:{entry['id']}")
    assert _books(org, today.replace(day=1), today)[1]["revenue"] == D("-1020")
    out = StringIO()
    call_command("fix_commission_undo_dates", stdout=out)
    assert "Would correct" in out.getvalue() and _books(org, today.replace(day=1), today)[1]["revenue"] == D("-1020")  # a dry run changes nothing
    call_command("fix_commission_undo_dates", "--apply", stdout=out)
    call_command("fix_commission_undo_dates", "--apply", stdout=out)  # running it again does nothing more
    assert _books(org, last_month, _month_end(last_month))[1]["revenue"] == 0
    assert _books(org, today.replace(day=1), today)[1]["revenue"] == 0
    assert _books(org)[0]["1160"]["balance"] == 0


def _close(org, owner, session, cash, electronic_float):
    with organization_context(org):
        from apps.mpesa.services import reconcile_session
        return reconcile_session(session=session, user=owner, actual_cash=cash, actual_float=electronic_float, reason="counted")


def test_commission_already_in_the_opening_float_counts_as_income_without_moving_the_float(agency):
    client, org, owner, outlet, today, last_month = agency
    with organization_context(org):
        from apps.mpesa.services import open_session, session_balances
        first = open_session(outlet=outlet, operator=owner, opening_cash="5000", opening_float="11045")
    # The first shift ever: all of its opening float could be commission, but not more.
    too_much = _record(client, outlet, last_month, "12000", "", "OPENING_FLOAT", key="o1", session_id=first.pk)
    assert too_much.status_code == 400 and "at most" in str(too_much.json())
    made = _record(client, outlet, last_month, "1020", "", "OPENING_FLOAT", key="o2", session_id=first.pk)
    assert made.status_code == 201, made.content
    row = made.json()
    assert row["paid_on"] == str(today) and "Already in the float" in row["notes"]
    with organization_context(org):
        assert session_balances(first) == (D("5000.00"), D("11045.00"))  # the float does not change
    accounts, last_pl, checks = _books(org, last_month, _month_end(last_month))
    assert last_pl["revenue"] == D("1020")  # September's income
    accounts, _, checks = _books(org)
    assert accounts["4010"]["balance"] == D("-1020") and accounts["1160"]["balance"] == 0
    assert checks["agency_float"]["reconciled"] and checks["agency_cash"]["reconciled"]
    month = next(m for m in client.get("/api/v1/mpesa/commission/").json()["months"] if m["month"] == str(last_month))
    assert D(str(month["commission"])) == D("1020")
    # Undone, the income comes back out and the float is still untouched.
    undone = client.post(f"/api/v1/mpesa/commission/{row['id']}/undo/", {"reason": "wrong month"}, format="json")
    assert undone.status_code == 200 and undone.json()["reversed_at"]
    accounts, pl, _ = _books(org)
    assert accounts["4010"]["balance"] == 0 and pl["revenue"] == 0


def test_a_shift_opens_with_what_the_last_one_closed_with_or_says_why(agency):
    client, org, owner, outlet, today, last_month = agency
    with organization_context(org):
        from apps.mpesa.services import open_session
        from apps.mpesa.commission import opening_room
        first = open_session(outlet=outlet, operator=owner, opening_cash="5000", opening_float="10000")
    _close(org, owner, first, "4000", "11000")
    with organization_context(org):
        from rest_framework.exceptions import ValidationError
        with pytest.raises(ValidationError, match="closed with cash 4,000.00 and float 11,000.00"):
            open_session(outlet=outlet, operator=owner, opening_cash="4000", opening_float="12000")
        # More float than the commission explains is refused; the commission alone explains the difference.
        with pytest.raises(ValidationError, match="at most"):
            open_session(outlet=outlet, operator=owner, opening_cash="4000", opening_float="12000",
                         commission={"period": str(last_month), "amount": "1500"})
        second = open_session(outlet=outlet, operator=owner, opening_cash="4000", opening_float="12000",
                              commission={"period": str(last_month), "amount": "1000"})
        assert (second.carried_cash, second.carried_float, second.opening_difference_reason) == (D("4000.00"), D("11000.00"), "")
        assert second.opening_commissions.get().amount == D("1000.00") and opening_room(second) == 0
    accounts, _, checks = _books(org)
    assert accounts["4010"]["balance"] == D("-1000") and checks["agency_float"]["reconciled"]
    # Nothing more of that opening float can be commission.
    again = _record(client, outlet, last_month, "1", "", "OPENING_FLOAT", key="o3", session_id=second.pk)
    assert again.status_code == 400
    _close(org, owner, second, "4000", "12000")
    with organization_context(org):
        third = open_session(outlet=outlet, operator=owner, opening_cash="0", opening_float="12000", difference_reason="Owner banked the cash")
        assert third.opening_difference_reason == "Owner banked the cash"
    # Through the API: a difference without a reason is refused with the numbers.
    _close(org, owner, third, "0", "12000")
    refused = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "50", "opening_float": "12000"}, format="json")
    assert refused.status_code == 400 and "Say why they differ" in str(refused.json())


def test_commission_paid_into_the_float_and_taken_from_the_drawer_works_like_a_withdrawal(agency):
    client, org, owner, outlet, today, last_month = agency
    with organization_context(org):
        from apps.mpesa.services import open_session, session_balances
        session = open_session(outlet=outlet, operator=owner, opening_cash="10000", opening_float="20000")
    made = _record(client, outlet, last_month, "3000", "", "AGENCY_FLOAT_TO_OWNER", key="w1", session_id=session.pk)
    assert made.status_code == 201, made.content
    with organization_context(org):
        assert session_balances(session) == (D("7000.00"), D("23000.00"))
    accounts, last_pl, _ = _books(org, last_month, _month_end(last_month))
    assert last_pl["revenue"] == D("3000")
    accounts, _, checks = _books(org)
    assert accounts["1000"]["balance"] == D("3000") and accounts["4010"]["balance"] == D("-3000")
    assert checks["agency_float"]["reconciled"] and checks["agency_cash"]["reconciled"]
    undone = client.post(f"/api/v1/mpesa/commission/{made.json()['id']}/undo/", {"reason": "test"}, format="json")
    assert undone.status_code == 200, undone.content
    with organization_context(org):
        assert session_balances(session) == (D("10000.00"), D("20000.00"))
    accounts, pl, checks = _books(org)
    assert accounts["1000"]["balance"] == 0 and accounts["4010"]["balance"] == 0 and pl["revenue"] == 0
    assert checks["agency_float"]["reconciled"] and checks["agency_cash"]["reconciled"]
