"""The owner's dashboard shows everything recorded so far, with figures that agree with the books."""
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


def test_everything_recorded_so_far_leaves_out_what_was_undone():
    owner = User.objects.create_user("records-owner", password="Safe-pass-1848")
    org = Organization.objects.create(name="Records shop", slug="records", owner=owner, enabled_modules=["inventory", "pos", "services", "mpesa", "reports"])
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    client = APIClient()
    client.force_login(owner)
    with organization_context(org):
        from apps.mpesa.models import MpesaOutlet
        from apps.mpesa.services import open_session, post_transaction, reverse_transaction
        outlet = MpesaOutlet.objects.create(store=Store.objects.create(name="Main"), display_name="Agent till")
        session = open_session(outlet=outlet, operator=owner, opening_cash="5000", opening_float="20000")
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="1000", user=owner, idempotency_key="d1")
        wrong, _ = post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="700", user=owner, idempotency_key="d2")
        reverse_transaction(original=wrong, user=owner, reason="Entered twice", idempotency_key="r1")
        post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", transaction_amount="400", user=owner, idempotency_key="w1")
    mmf = client.post("/api/v1/accounting/investments/", {"name": "CIC MMF", "annual_rate": "13"}, format="json").json()["id"]
    client.post("/api/v1/accounting/money-check/starting/", {"method": "MPESA", "amount": "10000", "idempotency_key": "start"}, format="json")
    moved = client.post(f"/api/v1/accounting/investments/{mmf}/move/", {"kind": "DEPOSIT", "amount": "3000", "source": "MPESA", "idempotency_key": "in"}, format="json").json()
    client.post(f"/api/v1/accounting/investments/movements/{moved['movements'][0]['id']}/undo/", {"reason": "Not done"}, format="json")
    records = client.get("/api/v1/inventory/dashboard/").json()["records"]
    agency = records["mpesa"]
    assert (agency["deposits"], D(str(agency["deposits_value"])), agency["withdrawals"], D(str(agency["withdrawals_value"]))) == (1, D("1000"), 1, D("400"))
    assert (agency["shifts_open"], agency["shifts_closed"], agency["outlets"]) == (1, 0, 1)
    assert (records["money"]["investments"], D(str(records["money"]["investments_value"]))) == (1, D("0"))  # the deposit was undone
    assert records["sales"]["completed"] == 0 and D(str(records["profit"]["profit"])) == 0
    assert records["catalogue"] is not None and records["stock"]["below_cost"] == []
