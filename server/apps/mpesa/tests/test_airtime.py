"""Airtime (credit) sold from the float: how each way of paying moves cash and float, and that it is never income."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounting.models import CashEntry, JournalLine
from apps.commerce.models import Sale
from apps.core.models import Store
from apps.mpesa.models import MpesaOutlet, MpesaTransaction
from apps.mpesa.monthly_report import month_data
from apps.mpesa.services import correct_transaction, open_session, post_transaction, reverse_transaction, session_balances

pytestmark = pytest.mark.django_db


@pytest.fixture
def shift(db):
    operator = User.objects.create_superuser("airtime-operator", "airtime@example.test", "test")
    outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="LinTech"), display_name="Main M-Pesa")
    return operator, open_session(outlet=outlet, operator=operator, opening_cash="2000", opening_float="3000")


def sell(shift, amount, paid_by, key, **extra):
    operator, session = shift
    return post_transaction(session=session, transaction_type="AIRTIME_SALE", transaction_amount=amount, paid_by=paid_by, user=operator,
                            idempotency_key=key, **extra)[0]


def test_each_way_of_paying_moves_cash_and_float_as_it_really_happens(shift):
    _, session = shift
    cash = sell(shift, "100", "CASH", "a1", customer_phone="0712 345 678")
    assert (cash.cash_delta, cash.float_delta, cash.customer_phone, cash.paid_by) == (Decimal("100"), Decimal("-100"), "254712345678", "CASH")
    assert session_balances(session) == (Decimal("2100"), Decimal("2900"))
    sell(shift, "50", "MPESA_FLOAT", "a2", provider_reference="sk12abc")  # paid back into the same line: no change
    assert session_balances(session) == (Decimal("2100"), Decimal("2900"))
    sell(shift, "200", "MPESA_OTHER", "a3")  # paid to the till: the float is spent, the money is outside the agency
    assert session_balances(session) == (Decimal("2100"), Decimal("2700"))
    assert not Sale.objects.exists()


def test_airtime_needs_a_way_of_paying_and_enough_float(shift):
    with pytest.raises(ValidationError, match="how the customer paid"):
        sell(shift, "100", "", "b1")
    with pytest.raises(ValidationError, match="electronic float"):
        sell(shift, "3500", "MPESA_FLOAT", "b2")  # the airtime still has to come out of the float first
    with pytest.raises(ValidationError, match="electronic float"):
        sell(shift, "3500", "CASH", "b3")


def test_airtime_is_never_income_in_the_books(shift):
    sale = sell(shift, "100", "CASH", "c1")
    lines = JournalLine.objects.filter(entry__source_key=f"agency:{sale.pk}")
    net = {}
    for line in lines:
        net[line.account.code] = net.get(line.account.code, 0) + line.debit - line.credit
    # Agency cash up, agency float down, and the equity they pass through cancels: an exchange, no income account.
    assert (net["1300"], net["1310"], net.get("3000", 0)) == (Decimal("100"), Decimal("-100"), 0)
    assert not any(code.startswith("4") for code in net)
    assert not CashEntry.objects.filter(kind="INCOME").exists()


def test_airtime_is_corrected_with_its_way_of_paying(shift):
    operator, session = shift
    wrong = sell(shift, "100", "CASH", "d1")
    right = correct_transaction(original=wrong, user=operator, key="fix", reason="Paid by M-Pesa to the till", amount="150", paid_by="MPESA_OTHER")
    assert (right.paid_by, right.amount, right.corrects_id) == ("MPESA_OTHER", Decimal("150"), wrong.pk)
    assert session_balances(session) == (Decimal("2000"), Decimal("2850"))
    reverse_transaction(original=right, user=operator, idempotency_key="undo", reason="Never sent")
    assert session_balances(session) == (Decimal("2000"), Decimal("3000"))


def test_desk_and_report_count_airtime_on_its_own(shift):
    operator, session = shift
    client = APIClient()
    client.force_login(operator)
    posted = client.post("/api/v1/mpesa/transactions/", {"session": session.pk, "transaction_type": "AIRTIME_SALE", "amount": "100", "paid_by": "CASH",
                         "customer_phone": "0712345678", "idempotency_key": "e1"}, format="json")
    assert posted.status_code == 201, posted.content
    assert posted.json()["paid_by"] == "CASH"
    desk = client.get("/api/v1/mpesa/dashboard/").json()
    assert (Decimal(str(desk["airtime"])), Decimal(str(desk["deposits"]))) == (Decimal("100"), 0)
    MpesaTransaction.objects.update(occurred_at=MpesaTransaction.objects.get().occurred_at.replace(year=2025, month=1))
    totals = month_data("2025-01")["totals"]
    assert (totals["AIRTIME_SALE"]["net"], totals["CUSTOMER_DEPOSIT"]["net"]) == (Decimal("100"), 0)
