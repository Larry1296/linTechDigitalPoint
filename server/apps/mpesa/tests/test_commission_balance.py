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
    return operator, open_session(outlet=outlet, operator=operator, opening_cash="5000", opening_float="5000")


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
