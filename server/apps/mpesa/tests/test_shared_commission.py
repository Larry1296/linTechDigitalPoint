"""Every agent business learns from the commission table the others confirmed, without seeing their records."""
from decimal import Decimal
from itertools import count

import pytest
from django.contrib.auth.models import User

from apps.core.models import Store
from apps.mpesa.models import MpesaOutlet
from apps.mpesa.services import open_session, post_transaction
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization

pytestmark = pytest.mark.django_db
numbers = count()


def agent(name):
    org = Organization.objects.create(name=name, slug=name.lower().replace(" ", "-"))
    with organization_context(org):
        operator = User.objects.create_superuser(f"{org.slug}-op", f"{org.slug}@example.test", "test")
        Membership.objects.update_or_create(user=operator, organization=org, defaults={"role": "OWNER", "status": "ACTIVE"})
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name=name), display_name="Agent line")
        session = open_session(outlet=outlet, operator=operator, opening_cash="50000", opening_float="50000", commission_balance="100")
    return org, operator, session


def deposit(business, amount, reading=None, kind="CUSTOMER_DEPOSIT"):
    org, operator, session = business
    with organization_context(org):
        return post_transaction(session=session, transaction_type=kind, transaction_amount=amount, user=operator,
                                idempotency_key=f"k{next(numbers)}", commission_balance=reading)[0]


def predicts(business, amount, kind="CUSTOMER_DEPOSIT"):
    from apps.mpesa.commission_learning import learn
    org, _, session = business
    with organization_context(org):
        return learn([session.outlet_id])[2].predict(kind, Decimal(amount))


def test_two_businesses_agreeing_teach_every_business():
    a, b, newcomer = agent("Shop A"), agent("Shop B"), agent("Shop C")
    deposit(a, "1000", "107.20")
    assert predicts(newcomer, "1000") is None and predicts(a, "1000") is None  # one business, one reading: not trusted
    deposit(b, "1000", "107.20")
    assert predicts(newcomer, "1000") == Decimal("7.20")
    assert predicts(a, "1000") == Decimal("7.20")


def test_amounts_two_businesses_found_earning_the_same_cover_the_band_between():
    a, b, newcomer = agent("Shop A"), agent("Shop B"), agent("Shop C")
    deposit(a, "700", "107.20", kind="CUSTOMER_WITHDRAWAL")
    deposit(b, "750", "107.20", kind="CUSTOMER_WITHDRAWAL")
    assert predicts(newcomer, "720", kind="CUSTOMER_WITHDRAWAL") == Decimal("7.20")
    assert predicts(newcomer, "800", kind="CUSTOMER_WITHDRAWAL") is None


def test_a_business_that_read_something_else_is_asked_again():
    a, b, c = agent("Shop A"), agent("Shop B"), agent("Shop C")
    deposit(a, "1000", "107.20")
    deposit(b, "1000", "107.20")
    deposit(c, "1000", "109")
    assert predicts(c, "1000") is None


def test_a_business_own_confirmed_figure_comes_first():
    a, b, c = agent("Shop A"), agent("Shop B"), agent("Shop C")
    deposit(a, "1000", "107.20")
    deposit(b, "1000", "107.20")
    deposit(c, "1000", "109")
    deposit(c, "1000", "118")
    assert predicts(c, "1000") == Decimal("9")


def test_the_learned_table_marks_what_came_from_other_agents():
    from apps.mpesa.commission_learning import learn
    a, b, newcomer = agent("Shop A"), agent("Shop B"), agent("Shop C")
    deposit(a, "1000", "107.20")
    deposit(b, "1000", "107.20")
    org, _, session = newcomer
    with organization_context(org):
        bands = learn([session.outlet_id])[2].bands()
    assert bands == [{"kind": "CUSTOMER_DEPOSIT", "label": "Deposits", "from": Decimal("1000.00"), "to": Decimal("1000.00"),
                      "earned": Decimal("7.20"), "seen": 1, "confirmed": True, "shared": True}]
