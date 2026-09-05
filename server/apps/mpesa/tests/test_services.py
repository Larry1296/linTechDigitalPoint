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
    post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="5000", user=operator, idempotency_key="deposit-1", provider_reference="ABC123XYZ")
    assert session_balances(session) == (Decimal("25000.00"), Decimal("25000.00"))
    post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", transaction_amount="3000", user=operator, idempotency_key="withdraw-1", provider_reference="DEF123XYZ")
    assert session_balances(session) == (Decimal("22000.00"), Decimal("28000.00"))
    assert not Sale.objects.exists()


@pytest.mark.django_db
def test_double_post_is_idempotent_and_reference_is_unique(mpesa_shift):
    operator, session = mpesa_shift
    first, created = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount=5000, user=operator, idempotency_key="click-once", provider_reference="ABC123XYZ")
    second, created_again = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount=5000, user=operator, idempotency_key="click-once", provider_reference="ABC123XYZ")
    assert created and not created_again and first == second
    assert session_balances(session) == (Decimal("25000.00"), Decimal("25000.00"))
    with pytest.raises(ValidationError, match="already been posted"):
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount=100, user=operator, idempotency_key="different-click", provider_reference="ABC123XYZ")


@pytest.mark.django_db
def test_reversal_restores_balances_and_preserves_original(mpesa_shift):
    operator, session = mpesa_shift
    original, _ = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount=5000, user=operator, idempotency_key="deposit")
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
        post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", transaction_amount=5000, user=operator, idempotency_key="too-much-cash")
    with pytest.raises(ValidationError, match="electronic float"):
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount=3000, user=operator, idempotency_key="too-much-float")
    assert not MpesaTransaction.objects.exists()


@pytest.mark.django_db
def test_reconciliation_freezes_expected_balances_and_requires_variance_reason(mpesa_shift):
    operator, session = mpesa_shift
    post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount=5000, user=operator, idempotency_key="reconcile-deposit")
    with pytest.raises(ValidationError, match="reason"):
        reconcile_session(session=session, user=operator, actual_cash=24900, actual_float=25000)
    result = reconcile_session(session=session, user=operator, actual_cash=24900, actual_float=25000, reason="Cash count short by KSh 100")
    assert result.expected_cash == Decimal("25000.00")
    assert result.cash_variance == Decimal("-100.00") and result.float_variance == 0
    session.refresh_from_db()
    assert session.status == "CLOSED"
