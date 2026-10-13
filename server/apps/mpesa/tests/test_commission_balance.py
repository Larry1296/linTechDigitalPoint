"""The commission balance read off the agent line after each deposit, withdrawal or airtime sale, kept with the transaction."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError

from apps.core.models import Store
from apps.mpesa.models import MpesaOutlet
from apps.mpesa.services import correct_transaction, open_session, post_transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def shift(db):
    operator = User.objects.create_superuser("commission-operator", "commission@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="LinTech"), display_name="Main M-Pesa")
    return operator, open_session(outlet=outlet, operator=operator, opening_cash="50000", opening_float="50000")


def post(shift, transaction_type, key, **extra):
    operator, session = shift
    return post_transaction(session=session, transaction_type=transaction_type, transaction_amount="500", user=operator, idempotency_key=key, **extra)[0]


def test_the_balance_is_kept_with_deposits_withdrawals_and_airtime(shift):
    assert post(shift, "CUSTOMER_DEPOSIT", "d1", commission_balance="1,250.50").commission_balance == Decimal("1250.50")
    assert post(shift, "CUSTOMER_WITHDRAWAL", "w1", commission_balance="1268").commission_balance == Decimal("1268.00")
    assert post(shift, "AIRTIME_SALE", "a1", paid_by="CASH", commission_balance="1270").commission_balance == Decimal("1270.00")


def test_the_balance_is_optional_and_never_negative(shift):
    assert post(shift, "CUSTOMER_DEPOSIT", "d2").commission_balance is None
    assert post(shift, "CUSTOMER_DEPOSIT", "d3", commission_balance="").commission_balance is None
    with pytest.raises(ValidationError, match="below zero"):
        post(shift, "CUSTOMER_DEPOSIT", "d4", commission_balance="-5")
    with pytest.raises(ValidationError, match="as a number"):
        post(shift, "CUSTOMER_WITHDRAWAL", "w2", commission_balance="abc")


def test_a_correction_keeps_the_balance_unless_a_new_one_is_given(shift):
    operator, _ = shift
    first = post(shift, "CUSTOMER_WITHDRAWAL", "w3", commission_balance="900")
    kept = correct_transaction(original=first, user=operator, key="c1", reason="typed 500, was 600", amount="600")
    assert kept.commission_balance == Decimal("900.00")
    fixed = correct_transaction(original=kept, user=operator, key="c2", reason="balance misread", amount="600", commission_balance="912")
    assert fixed.commission_balance == Decimal("912.00")


def learned(session):
    from apps.mpesa.commission_learning import earned, learn
    return earned(*learn([session.outlet_id]))


def record(shift, transaction_type, amount, key, reading=None, **extra):
    operator, session = shift
    return post_transaction(session=session, transaction_type=transaction_type, transaction_amount=amount, user=operator, idempotency_key=key,
                            commission_balance=reading, **extra)[0]


def test_the_rise_between_readings_is_what_each_transaction_earned(shift):
    _, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "m1", "100")
    second = record(shift, "CUSTOMER_WITHDRAWAL", "1500", "m2", "118")
    third = record(shift, "CUSTOMER_DEPOSIT", "700", "m3", "118")  # a deposit can earn nothing
    results = learned(session)
    assert results[second.pk] == (Decimal("18.00"), "measured")
    assert results[third.pk] == (Decimal("0.00"), "measured")


def test_the_app_fills_in_commission_it_has_learned_and_leaves_the_rest_unknown(shift):
    _, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "l1", "100")
    record(shift, "CUSTOMER_WITHDRAWAL", "1200", "l2", "118")
    record(shift, "CUSTOMER_WITHDRAWAL", "2000", "l3", "136")  # 1,200 and 2,000 both earned 18: one band
    between = record(shift, "CUSTOMER_WITHDRAWAL", "1500", "l4")  # no reading: lies inside the learned band
    same = record(shift, "CUSTOMER_WITHDRAWAL", "2000", "l5")  # no reading: an amount already measured
    unseen = record(shift, "CUSTOMER_WITHDRAWAL", "9000", "l6")  # beyond anything seen
    deposit = record(shift, "CUSTOMER_DEPOSIT", "1500", "l7")  # withdrawals teach nothing about deposits
    results = learned(session)
    assert results[between.pk] == (Decimal("18.00"), "learned")
    assert results[same.pk] == (Decimal("18.00"), "learned")
    assert results[unseen.pk] == (None, None)
    assert results[deposit.pk] == (None, None)
    from apps.mpesa.commission_learning import for_shift
    assert for_shift(session) == {"earned": Decimal("72.00"), "measured": 2, "learned": 2, "unknown": 3}


def test_an_unread_transaction_or_a_payout_in_between_measures_nothing(shift):
    _, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "u1", "100")
    record(shift, "CUSTOMER_DEPOSIT", "5000", "u2")  # not read: the next rise is two transactions' commission
    after_gap = record(shift, "CUSTOMER_WITHDRAWAL", "1000", "u3", "150")
    after_payout = record(shift, "CUSTOMER_WITHDRAWAL", "1000", "u4", "10")  # Safaricom paid the balance out
    results = learned(session)
    assert results[after_gap.pk] == (None, None)
    assert results[after_payout.pk] == (None, None)


def test_the_reading_a_shift_opens_with_measures_its_first_transaction(db):
    from apps.mpesa.api import money_in_operation
    from apps.mpesa.services import reconcile_session
    operator = User.objects.create_superuser("opening-reader", "opening@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Opening shop"), display_name="Till")
    first = open_session(outlet=outlet, operator=operator, opening_cash="5000", opening_float="5000", commission_balance="1,200")
    assert first.opening_commission_balance == Decimal("1200.00")
    assert money_in_operation(outlet)["commission_balance"] == Decimal("1200.00")
    shift = (operator, first)
    earned_first = record(shift, "CUSTOMER_WITHDRAWAL", "1000", "o1", "1212")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "o2")  # unread: the closing reading is still 1,212
    assert money_in_operation(outlet)["commission_balance"] == Decimal("1212.00")
    reconcile_session(session=first, user=operator, actual_cash="3000", actual_float="7000")
    second = open_session(outlet=outlet, operator=operator, opening_cash="3000", opening_float="7000", commission_balance="0")  # paid out
    after_payout = record((operator, second), "CUSTOMER_WITHDRAWAL", "1500", "o3", "18")
    results = learned(second)
    assert results[earned_first.pk] == (Decimal("12.00"), "measured")
    assert results[after_payout.pk] == (Decimal("18.00"), "measured")
    from apps.mpesa.commission_learning import for_shift
    assert for_shift(second) == {"earned": Decimal("18.00"), "measured": 1, "learned": 0, "unknown": 0}  # the opening is not a transaction
    other = MpesaOutlet.objects.create(store=outlet.store, display_name="Second till")
    with pytest.raises(ValidationError, match="below zero"):
        open_session(outlet=other, operator=operator, opening_cash="0", opening_float="0", commission_balance="-1")


def test_a_reading_taken_during_an_open_shift_measures_the_next_transaction(shift):
    from apps.mpesa.api import money_in_operation
    from apps.mpesa.services import reconcile_session, record_commission_balance
    operator, session = shift  # opened before the app asked for a reading
    unread = record(shift, "CUSTOMER_WITHDRAWAL", "1000", "r1")
    assert money_in_operation(session.outlet)["commission_balance"] is None
    assert money_in_operation(session.outlet)["open_session"] == session.pk
    record_commission_balance(session=session, user=operator, value="2,400")
    assert money_in_operation(session.outlet)["commission_balance"] == Decimal("2400.00")
    after = record(shift, "CUSTOMER_WITHDRAWAL", "1500", "r2", "2418")
    results = learned(session)
    assert results[unread.pk] == (None, None)
    assert results[after.pk] == (Decimal("18.00"), "measured")
    with pytest.raises(ValidationError, match="Enter the commission balance"):
        record_commission_balance(session=session, user=operator, value="")
    reconcile_session(session=session, user=operator, actual_cash="47500", actual_float="52500")
    assert money_in_operation(session.outlet)["commission_balance"] == Decimal("2418.00")
    with pytest.raises(ValidationError, match="closed"):
        record_commission_balance(session=session, user=operator, value="2500")


def test_the_balance_now_adds_what_the_app_worked_out_since_the_last_reading(shift):
    from apps.mpesa.api import money_in_operation
    _, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "b1", "100")
    record(shift, "CUSTOMER_WITHDRAWAL", "1200", "b2", "118")
    record(shift, "CUSTOMER_WITHDRAWAL", "2000", "b3", "136")  # 1,200 to 2,000 earn 18
    record(shift, "CUSTOMER_WITHDRAWAL", "1500", "b4")  # no reading: worked out as 18
    record(shift, "CUSTOMER_WITHDRAWAL", "2000", "b5")  # no reading: worked out as 18
    record(shift, "CUSTOMER_WITHDRAWAL", "9000", "b6")  # not known yet: adds nothing
    money = money_in_operation(session.outlet)
    assert money["commission_balance"] == Decimal("172.00")
    assert (money["commission_read"], money["commission_worked_out"], money["commission_unknown"]) == (Decimal("136.00"), Decimal("36.00"), 1)
    record(shift, "CUSTOMER_WITHDRAWAL", "1500", "b7", "250")  # a new reading starts again from it
    money = money_in_operation(session.outlet)
    assert (money["commission_balance"], money["commission_worked_out"], money["commission_unknown"]) == (Decimal("250.00"), Decimal("0"), 0)


def test_a_correction_stands_where_the_wrong_entry_was(shift):
    operator, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "c3", "100")
    wrong = record(shift, "CUSTOMER_WITHDRAWAL", "700", "c4", "118")
    later = record(shift, "CUSTOMER_WITHDRAWAL", "1500", "c5", "136")
    fixed = correct_transaction(original=wrong, user=operator, key="c6", reason="typed 700, was 1,300", amount="1300")
    results = learned(session)
    assert results[fixed.pk] == (Decimal("18.00"), "measured")
    assert results[later.pk] == (Decimal("18.00"), "measured")
    assert wrong.pk not in results


def test_a_reading_counts_when_the_unread_transactions_before_it_are_already_known(shift):
    _, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "g1", "100")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "g2", "112")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "g2b", "124")  # 1,000 earns 12, twice: confirmed
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "g3")  # not read, but known: 12
    new = record(shift, "CUSTOMER_WITHDRAWAL", "3000", "g4", "166")  # 166 - 124 - 12 = 30
    assert learned(session)[new.pk] == (Decimal("30.00"), "measured")


def test_the_form_asks_a_few_times_then_the_box_goes_away(shift):
    from apps.mpesa.commission_learning import advice
    _, session = shift
    outlet = session.outlet_id
    assert advice(outlet, "CUSTOMER_WITHDRAWAL", Decimal("1000")) == {"earned": None, "ask": True, "reason": "new"}
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "q1", "100")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "q2", "112")  # one measurement: not trusted yet
    assert advice(outlet, "CUSTOMER_WITHDRAWAL", Decimal("1000"))["ask"] is True
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "q3", "124")  # the same again: learned
    assert advice(outlet, "CUSTOMER_WITHDRAWAL", Decimal("1000")) == {"earned": Decimal("12.00"), "ask": False, "reason": None}
    assert advice(outlet, "CUSTOMER_DEPOSIT", Decimal("1000"))["ask"] is True  # deposits not learned yet
    for n in range(30):
        record(shift, "CUSTOMER_WITHDRAWAL", "1000", f"q-{n}")
    assert advice(outlet, "CUSTOMER_WITHDRAWAL", Decimal("1000"))["ask"] is False  # never asks again for a learned amount


def test_one_misread_balance_does_not_become_a_rate(shift):
    _, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "x1", "100")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "x2", "112")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "x3", "124")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "x4", "160")  # misread: 36
    unread = record(shift, "CUSTOMER_WITHDRAWAL", "1000", "x5")
    assert learned(session)[unread.pk] == (None, None)  # 12 then 36: not trusted until two agree again


def test_the_advice_endpoint(shift):
    from rest_framework.test import APIClient
    operator, session = shift
    client = APIClient()
    client.force_authenticate(operator)
    response = client.get(f"/api/v1/mpesa/transactions/commission-advice/?session={session.pk}&type=CUSTOMER_DEPOSIT&amount=500")
    assert response.status_code == 200 and response.json()["ask"] is True


def test_the_month_forecast_runs_the_pace_so_far_to_the_month_end(shift):
    import calendar
    from django.utils import timezone
    from apps.mpesa.commission_learning import forecast
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "f1", "100")  # the first reading measures nothing, but 1,000 is learned: 12
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "f2", "112")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "f3", "124")  # 12 each: learned
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "f4")  # worked out: 12
    record(shift, "CUSTOMER_DEPOSIT", "500", "f5")  # not worked out: counted at the average, 12
    from datetime import date
    today = timezone.localdate()
    days_left = sum(1 for d in range(today.day + 1, calendar.monthrange(today.year, today.month)[1] + 1)
                    if date(today.year, today.month, d).weekday() != 6)  # closed on Sundays
    result = forecast()
    assert (result["so_far"], result["days_left"], result["unknown"]) == (Decimal("60.00"), days_left, 1)
    if today.weekday() != 6:
        assert result["daily"] == Decimal("60.00") and result["forecast"] == Decimal("60.00") * (1 + days_left)


def test_sundays_count_neither_in_the_pace_nor_in_the_days_left(shift):
    import calendar
    from datetime import date, datetime, time, timedelta
    from django.utils import timezone
    from apps.mpesa.commission_learning import forecast
    from apps.mpesa.models import MpesaTransaction
    first = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)  # last month: a whole week of it
    monday = first + timedelta(days=(7 - first.weekday()) % 7)
    saturday = monday + timedelta(days=5)
    for n, reading in enumerate(["100", "112", "124", "136", "148", "160", "172"]):
        record(shift, "CUSTOMER_WITHDRAWAL", "1000", f"s{n}", reading)  # 12 each, 84 in all
    MpesaTransaction.objects.update(occurred_at=timezone.make_aware(datetime.combine(monday, time(10))))
    result = forecast(timezone.make_aware(datetime.combine(saturday, time(18))))
    last = calendar.monthrange(first.year, first.month)[1]
    left = sum(1 for d in range(saturday.day + 1, last + 1) if date(first.year, first.month, d).weekday() != 6)
    assert result["so_far"] == Decimal("84.00")
    assert result["daily"] == Decimal("14.00")  # 84 over Monday to Saturday: six working days
    assert (result["days_left"], result["forecast"]) == (left, Decimal("84.00") + Decimal("14.00") * left)


def test_the_agency_analysis_counts_working_days_hours_sizes_and_commission(shift):
    from datetime import date
    from rest_framework.test import APIClient
    from apps.mpesa.analysis import working_days
    operator, session = shift
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "an1", "100")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "an2", "112")
    record(shift, "CUSTOMER_WITHDRAWAL", "1000", "an3", "124")
    record(shift, "CUSTOMER_DEPOSIT", "7000", "an4")
    client = APIClient()
    client.force_authenticate(operator)
    data = client.get("/api/v1/mpesa/analysis/?days=12").json()
    assert data["working_days"] == 12 and len(data["days"]) == 12
    assert all(date.fromisoformat(day["date"]).weekday() != 6 for day in data["days"])  # never a Sunday
    assert working_days(date(2026, 10, 12), 2) == [date(2026, 10, 10), date(2026, 10, 12)]  # Saturday, then Monday
    from django.utils import timezone
    if timezone.localdate().weekday() != 6:
        today = data["days"][-1]
        assert (today["count"], Decimal(str(today["withdrawals"])), Decimal(str(today["deposits"])), Decimal(str(today["commission"]))) == (4, Decimal("3000"), Decimal("7000"), Decimal("36"))
        assert {row["label"]: row["count"] for row in data["sizes"]}["501 to 1,000"] == 3
        assert sum(row["count"] for row in data["hours"]) == 4
        assert data["unknown"] == 1  # the deposit: deposits not learned yet
        assert {row["kind"]: Decimal(str(row["amount"])) for row in data["commission_by_kind"]}["withdrawals"] == Decimal("36")
