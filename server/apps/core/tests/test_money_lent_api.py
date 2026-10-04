"""The Money lent page's API: record a loan, confirm repayments, correct mistakes; cashiers cannot lend."""
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


def test_owner_lends_and_confirms_repayments_through_the_api():
    owner = User.objects.create_user("lender", password="Safe-pass-1848")
    cashier = User.objects.create_user("till", password="Safe-pass-1848")
    org = Organization.objects.create(name="Lender shop", slug="lender", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    Membership.objects.create(user=cashier, organization=org, role="CASHIER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
    client = APIClient()
    client.force_login(owner)
    due = timezone.localdate() + timedelta(days=14)
    made = client.post("/api/v1/accounting/loans/", {"borrower_name": "Mary Achieng", "borrower_phone": "0712345678", "amount": "5000",
                       "method": "CASH", "due_date": str(due), "notes": "School fees", "idempotency_key": "k1"}, format="json")
    assert made.status_code == 201, made.content
    loan = made.json()
    assert (loan["status"], Decimal(loan["outstanding"]), loan["due_date"]) == ("OUTSTANDING", Decimal("5000"), str(due))
    paid = client.post(f"/api/v1/accounting/loans/{loan['id']}/repay/", {"amount": "5000", "method": "MPESA", "reference": "SJK4ABC123",
                       "idempotency_key": "p1"}, format="json")
    assert paid.status_code == 201 and paid.json()["status"] == "REPAID"
    undone = client.post(f"/api/v1/accounting/loans/repayments/{paid.json()['repayments'][0]['id']}/reverse/", {"reason": "Code wrong"}, format="json")
    assert undone.status_code == 200 and undone.json()["status"] == "OUTSTANDING"
    listed = client.get("/api/v1/accounting/loans/").json()
    assert Decimal(listed["total_outstanding"]) == Decimal("5000") and listed["overdue"] == 0
    till = APIClient()
    till.force_login(cashier)
    assert till.post("/api/v1/accounting/loans/", {"borrower_name": "X Y", "amount": "10", "method": "CASH", "due_date": str(due),
                     "idempotency_key": "k2"}, format="json").status_code == 403
