"""Cyber services paid at the till's own checkout: cash, M-Pesa, bank, a mix, or owed on credit by a named customer."""
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db.models import Sum

from apps.commerce.models import Checkout, Payment, Sale
from apps.cyber.models import CyberJob
from apps.tenancy.context import organization_context

from .test_income import cyber  # noqa: F401

pytestmark = pytest.mark.django_db
D = Decimal
CHECKOUTS = "/api/v1/commerce/pos/checkouts/"


def _customer(owner):
    response = owner.post("/api/v1/commerce/customers/", {"name": "Mary Wanjiku", "phone": "0712345678"}, format="json")
    assert response.status_code in (200, 201), response.content
    return response.json()["id"]


def _charge(client, printing, quantity="10", **extra):
    response = client.post("/api/v1/cyber/income/checkout/", {"lines": [{"option_id": printing.pk, "quantity": quantity}],
                           "idempotency_key": uuid4().hex, **extra}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def _pay(client, checkout, **values):
    return client.post(f"{CHECKOUTS}{checkout['id']}/pay/", values, format="json")


def test_a_visit_is_part_paid_in_cash_and_the_rest_owed_by_the_customer(cyber):
    owner, till, org, printing, _ = cyber
    customer = _customer(owner)
    checkout = _charge(till, printing, quantity="30", customer_id=customer)
    assert (checkout["kind"], checkout["total"], checkout["status"]) == ("CYBER", 300, "AWAITING")
    with organization_context(org):
        assert not CyberJob.objects.exists()  # nothing is recorded until it is paid
    # The desk picks up its own open checkout; the till does not see it.
    assert [row["id"] for row in till.get(f"{CHECKOUTS}?kind=cyber").json()["checkouts"]] == [checkout["id"]]
    assert owner.get(CHECKOUTS).json()["checkouts"] == []
    assert _pay(till, checkout, method="CASH", amount="100", cash_given="100").status_code == 201
    done = _pay(till, checkout, method="OWED", due_date="2026-11-01").json()
    assert done["status"] == "COMPLETED", done
    with organization_context(org):
        sale = Sale.objects.get(pk=done["sale_id"])
        assert (sale.channel, sale.total, sale.customer_id, str(sale.due_date)) == ("CYBER", D("300.00"), customer, "2026-11-01")
        assert sale.payments.aggregate(paid=Sum("amount"))["paid"] == D("100.00")
        job = sale.cyber_job
        assert (job.status, job.number, job.customer_id) == ("COMPLETED", sale.number, customer)
    assert owner.get("/api/v1/cyber/income/").json()["totals"]["all"] in (300, "300.00")


def test_credit_needs_a_named_customer(cyber):
    _, till, _, printing, _ = cyber
    checkout = _charge(till, printing)
    refused = _pay(till, checkout, method="OWED")
    assert refused.status_code == 400
    assert "customer" in str(refused.content)


def test_the_customer_who_owes_can_be_chosen_when_paying(cyber):
    owner, till, org, printing, _ = cyber
    customer = _customer(owner)
    checkout = _charge(till, printing)  # charged as a walk-in
    done = _pay(till, checkout, method="OWED", customer_id=customer, due_date="2026-11-01").json()
    assert (done["status"], done["customer_id"]) == ("COMPLETED", customer), done
    with organization_context(org):
        sale = Sale.objects.get(pk=done["sale_id"])
        assert (sale.customer_id, sale.cyber_job.customer_id, str(sale.due_date)) == (customer, customer, "2026-11-01")
        assert not sale.payments.exists()  # all of it is owed


def test_a_job_from_the_desk_is_paid_at_the_checkout_once(cyber):
    owner, till, org, printing, _ = cyber
    job = till.post("/api/v1/cyber/jobs/", {"lines": [{"variant_id": printing.variant_id, "quantity": "5"}]}, format="json").json()
    charged = till.post(f"/api/v1/cyber/jobs/{job['id']}/checkout/", {"idempotency_key": "a"}, format="json")
    assert charged.status_code == 201, charged.content
    again = till.post(f"/api/v1/cyber/jobs/{job['id']}/checkout/", {"idempotency_key": "b"}, format="json").json()
    assert again["id"] == charged.json()["id"]  # one checkout at a time per job
    done = _pay(till, charged.json(), method="BANK", reference="FT123").json()
    assert done["status"] == "COMPLETED", done
    with organization_context(org):
        stored = CyberJob.objects.get(pk=job["id"])
        assert (stored.status, stored.sale.total) == ("COMPLETED", D("50.00"))
        assert Payment.objects.get(sale=stored.sale).method == "BANK"
        assert Checkout.objects.get(pk=done["id"]).sale_id == stored.sale_id
