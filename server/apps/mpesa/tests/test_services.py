from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError

from apps.commerce.models import Sale
from apps.core.models import Store
from apps.mpesa.models import MpesaOutlet, MpesaTransaction
from apps.mpesa.services import open_session, post_transaction, reconcile_session, reverse_transaction, session_balances


@pytest.fixture
def mpesa_shift(db):
    operator = User.objects.create_superuser("mpesa-operator", "mpesa@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="LinTech"), display_name="Main M-Pesa")
    session = open_session(outlet=outlet, operator=operator, opening_cash="20000", opening_float="30000")
    return operator, session


@pytest.mark.django_db
def test_deposit_and_withdrawal_move_balances_but_create_no_revenue(mpesa_shift):
    operator, session = mpesa_shift
    post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount="5000", user=operator, idempotency_key="deposit-1", provider_reference="ABC123XYZ")
    assert session_balances(session) == (Decimal("25000.00"), Decimal("25000.00"))
    post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount="3000", user=operator, idempotency_key="withdraw-1", provider_reference="DEF123XYZ")
    assert session_balances(session) == (Decimal("22000.00"), Decimal("28000.00"))
    assert not Sale.objects.exists()


@pytest.mark.django_db
def test_double_post_is_idempotent_and_reference_is_unique(mpesa_shift):
    operator, session = mpesa_shift
    first, created = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=5000, user=operator, idempotency_key="click-once", provider_reference="ABC123XYZ")
    second, created_again = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=5000, user=operator, idempotency_key="click-once", provider_reference="ABC123XYZ")
    assert created and not created_again and first == second
    assert session_balances(session) == (Decimal("25000.00"), Decimal("25000.00"))
    with pytest.raises(ValidationError, match="already been posted"):
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=100, user=operator, idempotency_key="different-click", provider_reference="ABC123XYZ")


@pytest.mark.django_db
def test_reversal_restores_balances_and_preserves_original(mpesa_shift):
    operator, session = mpesa_shift
    original, _ = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=5000, user=operator, idempotency_key="deposit")
    reversal, created = reverse_transaction(original=original, user=operator, idempotency_key="reverse-deposit", reason="Operator entered wrong amount")
    assert created and reversal.reversal_of == original
    assert MpesaTransaction.objects.filter(pk=original.pk).exists()
    assert session_balances(session) == (Decimal("20000.00"), Decimal("30000.00"))


@pytest.mark.django_db
def test_insufficient_cash_and_float_are_rejected(mpesa_shift):
    operator, session = mpesa_shift
    session.opening_cash = Decimal("2000")
    session.opening_float = Decimal("1000")
    session.save()
    with pytest.raises(ValidationError, match="physical cash"):
        post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=5000, user=operator, idempotency_key="too-much-cash")
    with pytest.raises(ValidationError, match="electronic float"):
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=3000, user=operator, idempotency_key="too-much-float")
    assert not MpesaTransaction.objects.exists()


@pytest.mark.django_db
def test_reconciliation_freezes_expected_balances_and_requires_variance_reason(mpesa_shift):
    operator, session = mpesa_shift
    post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=5000, user=operator, idempotency_key="reconcile-deposit")
    with pytest.raises(ValidationError, match="reason"):
        reconcile_session(session=session, user=operator, actual_cash=24900, actual_float=25000)
    result = reconcile_session(session=session, user=operator, actual_cash=24900, actual_float=25000, reason="Cash count short by KSh 100")
    assert result.expected_cash == Decimal("25000.00")
    assert result.cash_variance == Decimal("-100.00") and result.float_variance == 0
    session.refresh_from_db()
    assert session.status == "CLOSED"


@pytest.mark.django_db
def test_cash_is_counted_note_by_note_at_opening_and_closing(db):
    operator = User.objects.create_superuser("counter", "counter@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Counter shop"), display_name="Till")
    count = {"1000": 10, "500": 4, "200": 5, "100": 7, "50": 3, "coins": "85"}  # 10,000 + 2,000 + 1,000 + 700 + 150 + 85
    session = open_session(outlet=outlet, operator=operator, opening_cash=None, opening_float="30000", cash_count=count)
    assert session.opening_cash == Decimal("13935.00")
    assert session.opening_cash_count == {"1000": 10, "500": 4, "200": 5, "100": 7, "50": 3, "coins": "85.00"}
    post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount="1000", user=operator,
                     idempotency_key="dep", provider_reference="QWE123RTY")
    closing = reconcile_session(session=session, user=operator, actual_cash=None, actual_float="29000",
                                cash_count={**count, "1000": 11})
    assert (closing.actual_cash, closing.cash_variance, closing.float_variance) == (Decimal("14935.00"), 0, 0)
    assert closing.cash_count["1000"] == 11


@pytest.mark.django_db
def test_a_cash_count_that_disagrees_or_is_malformed_is_refused(db):
    operator = User.objects.create_superuser("counter2", "counter2@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Counter shop 2"), display_name="Till")
    for count, cash in [({"1000": 2}, "1500"), ({"1000": -1}, None), ({"1000": "2.5"}, None), ({"20": 3}, None), ({"coins": "-5"}, None)]:
        with pytest.raises(ValidationError):
            open_session(outlet=outlet, operator=operator, opening_cash=cash, opening_float="0", cash_count=count)
    assert open_session(outlet=outlet, operator=operator, opening_cash="2000", opening_float="0", cash_count={"1000": 2}).opening_cash == 2000


@pytest.mark.django_db
def test_desk_api_opens_shows_money_in_operation_and_closes_with_counts(db):
    from rest_framework.test import APIClient
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership, Organization, OrganizationSubscription
    owner = User.objects.create_user("desk-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Desk", slug="desk", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Desk shop"), display_name="Till")
    client = APIClient()
    client.force_login(owner)
    assert client.get("/api/v1/mpesa/dashboard/").json()["in_operation"] == {"total": 0, "opening": 0}
    opened = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "2150.00", "opening_float": "5000",
                         "cash_count": {"1000": 2, "500": 0, "200": 0, "100": 1, "50": 1, "coins": "0"}}, format="json")
    assert opened.status_code == 201, opened.content
    board = client.get("/api/v1/mpesa/dashboard/")
    assert board.status_code == 200, board.content
    assert {k: Decimal(str(v)) for k, v in board.json()["in_operation"].items()} == {"total": Decimal("7150"), "opening": Decimal("7150")}
    closed = client.post(f"/api/v1/mpesa/sessions/{opened.json()['id']}/reconcile/", {"actual_cash": "2150.00", "actual_float": "5000",
                         "cash_count": {"1000": 2, "100": 1, "50": 1}}, format="json")
    assert closed.status_code == 201, closed.content
    assert closed.json()["cash_count"]["1000"] == 2 and Decimal(closed.json()["cash_variance"]) == 0


@pytest.mark.django_db
def test_outlet_money_in_operation_is_due_every_day_but_sunday(db, monkeypatch):
    import datetime
    from django.utils import timezone
    from apps.mpesa.api import money_in_operation
    operator = User.objects.create_superuser("due-owner", "due@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Due shop"), display_name="Till", agent_reference="123456", store_number="654321")
    real = timezone.localdate
    def on(day):  # "today" is this date; converting stored times still works normally
        monkeypatch.setattr(timezone, "localdate", lambda value=None, *a, **k: day if value is None else real(value, *a, **k))
    today = real()
    monday = today + datetime.timedelta(days=(0 - today.weekday()) % 7 or 7)
    on(monday)
    assert money_in_operation(outlet) == {"cash": None, "float": None, "total": None, "updated_on": None, "due": True,
                                          "cash_count": {}, "commission_balance": None, "commission_read": None,
                                          "commission_worked_out": 0, "commission_paid_out": 0, "commission_unknown": 0, "open_session": None}
    on(monday + datetime.timedelta(days=6))  # Sunday: nothing is expected
    assert money_in_operation(outlet)["due"] is False
    session = open_session(outlet=outlet, operator=operator, opening_cash="3000", opening_float="7000")
    on(real(session.opened_at))
    state = money_in_operation(outlet)
    assert (state["cash"], state["float"], state["total"], state["due"]) == (Decimal("3000"), Decimal("7000"), Decimal("10000"), False)
    reconcile_session(session=session, user=operator, actual_cash="2900", actual_float="7000", reason="Short 100")
    on(real(session.opened_at) + datetime.timedelta(days=1))
    state = money_in_operation(outlet)
    assert state["total"] == Decimal("9900") and state["due"] is (state["updated_on"].weekday() != 5)


@pytest.mark.django_db
def test_outlet_can_be_edited_deactivated_and_deleted_only_without_history(db):
    from rest_framework.test import APIClient
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership, Organization, OrganizationSubscription
    owner = User.objects.create_user("crud-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Crud", slug="crud", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Crud shop")
    client = APIClient()
    client.force_login(owner)
    made = client.post("/api/v1/mpesa/outlets/", {"display_name": "Till", "agent_reference": "111", "store_number": "222"}, format="json").json()
    edited = client.patch(f"/api/v1/mpesa/outlets/{made['id']}/", {"display_name": "Main till", "store_number": "333"}, format="json")
    assert edited.status_code == 200 and (edited.json()["display_name"], edited.json()["store_number"]) == ("Main till", "333")
    assert client.delete(f"/api/v1/mpesa/outlets/{made['id']}/").status_code == 204
    kept = client.post("/api/v1/mpesa/outlets/", {"display_name": "Busy till"}, format="json").json()
    assert client.post("/api/v1/mpesa/sessions/", {"outlet": kept["id"], "opening_cash": "0", "opening_float": "0"}, format="json").status_code == 201
    assert client.patch(f"/api/v1/mpesa/outlets/{kept['id']}/", {"active": False}, format="json").status_code == 400
    refused = client.delete(f"/api/v1/mpesa/outlets/{kept['id']}/")
    assert refused.status_code == 400 and "Deactivate" in refused.json()["detail"]


@pytest.mark.django_db
def test_deposit_takes_optional_number_and_id_withdrawal_only_amount_and_codes_follow(mpesa_shift):
    from apps.mpesa.services import add_provider_reference
    operator, session = mpesa_shift
    base = dict(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="2500", user=operator)
    # Number and ID are optional, but checked when given.
    for phone, id_number in [("12345", "12345678"), ("0712345678", "12"), ("", "ID-12")]:
        with pytest.raises(ValidationError):
            post_transaction(**base, idempotency_key=f"bad-{phone}-{id_number}", customer_phone=phone, customer_id_number=id_number)
    for phone, id_number, stored in [("", "", ("", "")), ("0712345678", "", ("254712345678", "")), ("  ", "A1234567", ("", "A1234567"))]:
        bare, _ = post_transaction(**{**base, "transaction_amount": "10"}, idempotency_key=f"optional-{phone}-{id_number}", customer_phone=phone, customer_id_number=id_number)
        assert (bare.customer_phone, bare.customer_id_number) == stored
    entry, _ = post_transaction(**base, idempotency_key="full", customer_phone="+254 712 345 678", customer_id_number="12 345 678")
    assert (entry.customer_name, entry.customer_phone, entry.customer_id_number, entry.provider_reference) == ("", "254712345678", "12345678", None)
    assert add_provider_reference(entry=entry, reference=" sjk4abc123 ", user=operator).provider_reference == "SJK4ABC123"
    with pytest.raises(ValidationError, match="already has"):
        add_provider_reference(entry=entry, reference="OTHER12345", user=operator)
    withdrawal, _ = post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", transaction_amount="1000", user=operator,
                                     idempotency_key="withdraw-only-amount")
    assert (withdrawal.customer_phone, withdrawal.customer_id_number, withdrawal.provider_reference) == ("", "", None)
    with pytest.raises(ValidationError, match="another transaction"):
        add_provider_reference(entry=withdrawal, reference="SJK4ABC123", user=operator)
    assert add_provider_reference(entry=withdrawal, reference="TXN9876543", user=operator).provider_reference == "TXN9876543"


@pytest.mark.django_db
def test_closing_a_shift_starts_the_desk_figures_afresh_but_keeps_the_records(db):
    from rest_framework.test import APIClient
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership, Organization, OrganizationSubscription
    owner = User.objects.create_user("fresh-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Fresh", slug="fresh", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Fresh shop"), display_name="Till")
    client = APIClient()
    client.force_login(owner)
    first = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "1000", "opening_float": "5000"}, format="json").json()
    client.post("/api/v1/mpesa/transactions/", {"session": first["id"], "transaction_type": "CUSTOMER_DEPOSIT", "amount": "500",
                "customer_phone": "0712345678", "customer_id_number": "12345678", "idempotency_key": "d1"}, format="json")
    board = client.get("/api/v1/mpesa/dashboard/").json()
    assert (Decimal(str(board["deposits"])), board["transaction_count"]) == (Decimal("500"), 1)
    client.post(f"/api/v1/mpesa/sessions/{first['id']}/reconcile/", {"actual_cash": "1500", "actual_float": "4500"}, format="json")
    board = client.get("/api/v1/mpesa/dashboard/").json()
    assert (board["session"], board["deposits"], board["withdrawals"], board["transaction_count"]) == (None, 0, 0, 0)
    second = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "1500", "opening_float": "4500"}, format="json").json()
    board = client.get("/api/v1/mpesa/dashboard/").json()
    assert board["session"]["id"] == second["id"] and (board["deposits"], board["transaction_count"]) == (0, 0)
    with organization_context(org):
        assert MpesaTransaction.objects.filter(session_id=first["id"]).count() == 1  # the closed shift's record is kept


@pytest.mark.django_db
def test_monthly_report_is_offered_once_a_month_ends_and_downloads_a_pdf(db):
    import datetime
    from django.utils import timezone
    from rest_framework.test import APIClient
    from apps.core.models import AuditLog
    from apps.mpesa.models import MpesaSession
    from apps.mpesa.monthly_report import month_data
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership, Organization, OrganizationSubscription
    owner = User.objects.create_user("report-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Report shop", slug="report", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    with organization_context(org):
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Report shop"), display_name="Main till", agent_reference="123456", store_number="654321")
        session = open_session(outlet=outlet, operator=owner, opening_cash="1000", opening_float="5000")
        deposit, _ = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="500", user=owner, idempotency_key="d1",
                                      customer_phone="0712345678", customer_id_number="12345678")
        wrong, _ = post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", transaction_amount="200", user=owner, idempotency_key="w1")
        reverse_transaction(original=wrong, user=owner, idempotency_key="r1", reason="Customer cancelled")
        reconcile_session(session=session, user=owner, actual_cash="1500", actual_float="4500")
        # Move the shift into last month.
        last_month = (timezone.localdate().replace(day=1) - datetime.timedelta(days=1)).replace(day=10)
        moved = timezone.make_aware(datetime.datetime.combine(last_month, datetime.time(9)))
        MpesaSession.objects.filter(pk=session.pk).update(opened_at=moved, closed_at=moved + datetime.timedelta(hours=9))
        MpesaTransaction.objects.filter(session=session).update(occurred_at=moved + datetime.timedelta(hours=1))
        month = f"{last_month:%Y-%m}"
        data = month_data(month)
        assert data["totals"]["CUSTOMER_DEPOSIT"]["net"] == Decimal("500") and data["totals"]["CUSTOMER_WITHDRAWAL"] == {
            "label": "Withdrawal", "count": 1, "reversed": 1, "net": Decimal("0")}
        assert (data["first_opening"], data["last_closing"], data["reversals"]) == (Decimal("6000"), Decimal("6000"), 1)
    assert client.get("/api/v1/mpesa/reports/months/").json()[0]["month"] == month
    response = client.get(f"/api/v1/mpesa/reports/monthly/?month={month}")
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF") and f"mpesa-report-{month}.pdf" in response["Content-Disposition"]
    assert client.get(f"/api/v1/mpesa/reports/monthly/?month={timezone.localdate():%Y-%m}").status_code == 400  # month not over
    with organization_context(org):
        assert AuditLog.objects.filter(action="MPESA_MONTHLY_REPORT", object_id=month).exists()


@pytest.mark.django_db
def test_a_reversed_transaction_is_not_counted_on_the_desk(db):
    from rest_framework.test import APIClient
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership, Organization, OrganizationSubscription
    owner = User.objects.create_user("reverse-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Reverse", slug="reverse", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Reverse shop"), display_name="Till")
    client = APIClient()
    client.force_authenticate(owner)
    shift = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "1000", "opening_float": "5000"}, format="json").json()
    deposit = lambda key, amount: client.post("/api/v1/mpesa/transactions/", {"session": shift["id"], "transaction_type": "CUSTOMER_DEPOSIT",
        "amount": amount, "customer_phone": "0712345678", "customer_id_number": "12345678", "idempotency_key": key}, format="json").json()
    deposit("kept", "500")
    wrong = deposit("wrong", "700")
    assert client.post(f"/api/v1/mpesa/transactions/{wrong['id']}/reverse/", {"reason": "Customer cancelled", "idempotency_key": "rev"},
                       format="json").status_code == 201
    board = client.get("/api/v1/mpesa/dashboard/").json()
    assert (Decimal(str(board["deposits"])), board["transaction_count"]) == (Decimal("500"), 1)


@pytest.mark.django_db
def test_a_transaction_is_corrected_by_reversing_it_and_recording_the_right_one(mpesa_shift):
    from apps.mpesa.services import correct_transaction
    operator, session = mpesa_shift  # opens with 20,000 cash and 30,000 float
    wrong, _ = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="700", user=operator, idempotency_key="dep",
                                customer_phone="0712345678", customer_id_number="12345678", provider_reference="SJK4ABC123")
    with pytest.raises(ValidationError, match="what was wrong"):
        correct_transaction(original=wrong, user=operator, key="fix", reason="", amount="500")
    fixed = correct_transaction(original=wrong, user=operator, key="fix", reason="Typed 700, customer deposited 500", amount="500",
                                customer_phone="0798765432")
    assert (fixed.amount, fixed.customer_phone, fixed.customer_id_number, fixed.provider_reference, fixed.corrects_id) == (
        Decimal("500.00"), "254798765432", "12345678", "SJK4ABC123", wrong.pk)
    assert session_balances(session) == (Decimal("20500.00"), Decimal("29500.00"))  # as if only the 500 happened
    wrong.refresh_from_db()
    assert wrong.provider_reference is None and hasattr(wrong, "reversal") and "moved to its correction" in wrong.notes
    assert correct_transaction(original=wrong, user=operator, key="fix", reason="again", amount="500") == fixed  # a retry changes nothing
    with pytest.raises(ValidationError, match="already reversed or corrected"):
        correct_transaction(original=wrong, user=operator, key="fix-2", reason="again", amount="400")


@pytest.mark.django_db
def test_a_returning_depositor_is_found_by_phone_number(db):
    from rest_framework.test import APIClient
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership, Organization, OrganizationSubscription
    owner = User.objects.create_user("lookup-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Lookup", slug="lookup", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Lookup shop"), display_name="Till")
        session = open_session(outlet=outlet, operator=owner, opening_cash="1000", opening_float="5000")
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="200", user=owner, idempotency_key="first",
                         customer_phone="0712345678", customer_id_number="34299508")
    client = APIClient()
    client.force_authenticate(owner)
    found = client.get("/api/v1/mpesa/customers/lookup/?phone=+254 712 345 678").json()
    assert (found["found"], found["id_number"], found["visits"]) == (True, "34299508", 1)
    assert client.get("/api/v1/mpesa/customers/lookup/?phone=0700000000").json()["found"] is False
    assert client.get("/api/v1/mpesa/customers/lookup/?phone=123").json() == {"found": False}


@pytest.mark.django_db
def test_money_in_operation_is_corrected_by_a_manager_with_a_reason(mpesa_shift):
    operator, session = mpesa_shift
    with pytest.raises(ValidationError, match="Say why"):
        post_transaction(session=session, transaction_type="ADJUSTMENT", transaction_amount="5000", user=operator, idempotency_key="adjust-0",
                         cash_delta="-5000", float_delta="0")
    entry, _ = post_transaction(session=session, transaction_type="ADJUSTMENT", transaction_amount="5500", user=operator, idempotency_key="adjust-1",
                                cash_delta="-5000", float_delta="-500", notes="Opening cash was counted twice")
    assert entry.provider_reference is None
    assert session_balances(session) == (Decimal("15000.00"), Decimal("29500.00"))
    with pytest.raises(ValidationError, match="physical cash"):
        post_transaction(session=session, transaction_type="ADJUSTMENT", transaction_amount="20000", user=operator, idempotency_key="adjust-2",
                         cash_delta="-20000", float_delta="0", notes="Too much")
    reverse_transaction(original=entry, user=operator, idempotency_key="undo-adjust", reason="Wrong shift")
    assert session_balances(session) == (Decimal("20000.00"), Decimal("30000.00"))


@pytest.mark.django_db
def test_a_closed_shifts_records_can_be_opened_again_by_its_time(db):
    from rest_framework.test import APIClient
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership, Organization, OrganizationSubscription
    owner = User.objects.create_user("past-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Past", slug="past", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Past shop"), display_name="Till")
    client = APIClient()
    client.force_login(owner)
    empty = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "1000", "opening_float": "5000"}, format="json").json()
    client.post(f"/api/v1/mpesa/sessions/{empty['id']}/reconcile/", {"actual_cash": "1000", "actual_float": "5000"}, format="json")
    first = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "1000", "opening_float": "5000"}, format="json").json()
    client.post("/api/v1/mpesa/transactions/", {"session": first["id"], "transaction_type": "CUSTOMER_DEPOSIT", "amount": "500",
                "customer_phone": "0712345678", "customer_id_number": "12345678", "idempotency_key": "p1"}, format="json")
    assert client.get("/api/v1/mpesa/sessions/past/").json() == []  # still open: it is on the desk
    client.post(f"/api/v1/mpesa/sessions/{first['id']}/reconcile/", {"actual_cash": "1500", "actual_float": "4500"}, format="json")
    second = client.post("/api/v1/mpesa/sessions/", {"outlet": outlet.pk, "opening_cash": "1500", "opening_float": "4500"}, format="json").json()
    client.post("/api/v1/mpesa/transactions/", {"session": second["id"], "transaction_type": "CUSTOMER_DEPOSIT", "amount": "200",
                "customer_phone": "0712345678", "customer_id_number": "12345678", "idempotency_key": "p2"}, format="json")
    past = client.get("/api/v1/mpesa/sessions/past/").json()
    assert [(row["id"], row["records"]) for row in past] == [(first["id"], 1)]  # the empty shift has nothing to open
    assert past[0]["closed_at"] and Decimal(past[0]["closing_cash"]) == Decimal("1500")
    records = client.get(f"/api/v1/mpesa/transactions/?session={first['id']}").json()
    assert [(row["session"], Decimal(row["amount"])) for row in records] == [(first["id"], Decimal("500"))]


@pytest.mark.django_db
def test_float_top_up_says_whether_the_money_came_from_the_drawer_or_from_outside(mpesa_shift):
    operator, session = mpesa_shift
    with pytest.raises(ValidationError, match="where the float money came from"):
        post_transaction(session=session, transaction_type="FLOAT_TOPUP", transaction_amount="1000", user=operator, idempotency_key="topup-0")
    # Cash from the drawer turned into float: the money in operation stays the same.
    post_transaction(session=session, transaction_type="FLOAT_TOPUP", transaction_amount="1000", user=operator, idempotency_key="topup-1", paid_by="DRAWER")
    assert session_balances(session) == (Decimal("19000.00"), Decimal("31000.00"))
    # New money from outside the agency: only the float goes up.
    outside, _ = post_transaction(session=session, transaction_type="FLOAT_TOPUP", transaction_amount="5000", user=operator, idempotency_key="topup-2", paid_by="OUTSIDE")
    assert (outside.paid_by, outside.cash_delta, outside.float_delta) == ("OUTSIDE", Decimal("0.00"), Decimal("5000.00"))
    assert session_balances(session) == (Decimal("19000.00"), Decimal("36000.00"))
    reverse_transaction(original=outside, user=operator, idempotency_key="topup-2-undo", reason="entered twice")
    assert session_balances(session) == (Decimal("19000.00"), Decimal("31000.00"))
