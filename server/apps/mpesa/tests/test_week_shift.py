from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog, Store
from apps.mpesa.models import MpesaMoneyCheck, MpesaOutlet
from apps.mpesa.services import open_session, post_transaction, reconcile_session
from apps.mpesa.week_shift import CHECKS_PER_WEEK, check_days, count, due_check, week_end

MONDAY = date(2026, 11, 23)


def at(day, hour=8):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=hour))


@pytest.fixture
def week(db):
    owner = User.objects.create_superuser("agency-owner", "owner@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="LinTech"), display_name="Main M-Pesa")
    with mock.patch("django.utils.timezone.now", return_value=at(MONDAY)):
        session = open_session(outlet=outlet, operator=owner, opening_cash="20000", opening_float="30000")
    return owner, session


def test_a_shift_opened_in_the_week_runs_to_its_saturday_and_one_opened_on_the_weekend_to_the_next():
    saturday = date(2026, 11, 28)
    assert {week_end(MONDAY + timedelta(days=n)) for n in range(5)} == {saturday}
    assert week_end(saturday) == week_end(saturday + timedelta(days=1)) == date(2026, 12, 5)
    # Surprise checks fall between the opening count and the closing one, never on a Sunday.
    assert check_days(MONDAY, saturday) == [MONDAY + timedelta(days=n) for n in range(1, 5)]
    assert check_days(date(2026, 11, 26), saturday) == [date(2026, 11, 27)]


@pytest.mark.django_db
def test_opening_sets_the_week_and_hides_surprise_checks_on_random_working_days(week):
    _, session = week
    assert session.runs_until == date(2026, 11, 28)
    checks = list(session.money_checks.all())
    assert len(checks) == CHECKS_PER_WEEK
    days = [timezone.localdate(check.due_at) for check in checks]
    assert len(set(days)) == CHECKS_PER_WEEK and all(MONDAY < day < session.runs_until for day in days)
    assert all(9 <= timezone.localtime(check.due_at).hour < 17 for check in checks)
    with mock.patch("django.utils.timezone.now", return_value=at(MONDAY, 20)):
        assert due_check(session) is None  # none due on the opening day


@pytest.mark.django_db
def test_a_due_check_compares_the_total_money_and_needs_the_owners_reason_when_it_differs(week):
    owner, session = week
    first = session.money_checks.order_by("due_at").first()
    post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="5000", user=owner, idempotency_key="d-1")
    later = first.due_at + timedelta(minutes=5)
    with mock.patch("django.utils.timezone.now", return_value=later):
        assert due_check(session) == first
        with pytest.raises(ValidationError, match="-500.00 against the records"):
            count(session=session, user=owner, actual_cash="25000", actual_float="24500")
        checked = count(session=session, user=owner, actual_cash="25000", actual_float="24500", reason="Float sent to the shop till")
        assert due_check(session) is None
    assert checked.pk == first.pk and checked.difference == Decimal("-500") and checked.expected_float == Decimal("25000")
    assert AuditLog.objects.get(action="MPESA_MONEY_CHECK").after["difference"] == "-500.00"


@pytest.mark.django_db
def test_the_owner_can_check_any_time_and_a_wrong_split_with_the_right_total_is_flagged(week):
    owner, session = week
    with mock.patch("django.utils.timezone.now", return_value=at(MONDAY, 12)):
        # A 1,000 deposit not recorded: the total agrees, the split does not.
        check = count(session=session, user=owner, actual_cash="21000", actual_float="29000")
    from apps.mpesa.week_shift import check_row
    row = check_row(check)
    assert check.due_at is None and row["difference"] == 0 and row["split_off"] == Decimal("1000")
    assert session.money_checks.count() == CHECKS_PER_WEEK + 1


@pytest.mark.django_db
def test_an_employee_counts_blind_only_when_a_check_is_due_and_the_owner_sees_the_difference(week):
    owner, session = week
    from apps.tenancy.models import Membership, Organization
    worker = User.objects.create_user("desk-worker", first_name="Jane")
    Membership.objects.update_or_create(user=worker, organization=Organization.objects.get(), defaults={"role": "EMPLOYEE", "status": "ACTIVE", "open_pages": ["mpesa"]})
    with mock.patch("django.utils.timezone.now", return_value=at(MONDAY, 12)):
        with pytest.raises(ValidationError, match="No money check is due"):
            count(session=session, user=worker, actual_cash="20000", actual_float="30000")
    due = session.money_checks.order_by("due_at").first()
    with mock.patch("django.utils.timezone.now", return_value=due.due_at + timedelta(hours=1)):
        check = count(session=session, user=worker, actual_cash="19900", actual_float="30000")
    assert check.difference == Decimal("-100") and "for the owner to check" in check.reason


@pytest.mark.django_db
def test_closing_the_week_leaves_missed_checks_on_record_and_stops_asking(week):
    owner, session = week
    with mock.patch("django.utils.timezone.now", return_value=at(date(2026, 11, 28), 18)):
        assert due_check(session) is not None  # both have come due, nobody counted
        reconcile_session(session=session, user=owner, actual_cash="20000", actual_float="30000")
        session.refresh_from_db()
        assert due_check(session) is None
    assert MpesaMoneyCheck.objects.filter(session=session, counted_at__isnull=True).count() == CHECKS_PER_WEEK
