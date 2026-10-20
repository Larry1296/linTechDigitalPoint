"""Cyber services paid at the same checkout as the till (commerce/checkout.py).

A visit (services just done for a customer) or a job from the desk is charged: its amount is worked out by rehearsing
the real job and sale (rolled back), and frozen in a Checkout of kind CYBER. The customer then pays as at the till: cash,
the till, a prompt, bank, or owed by a named customer, in one way or several. Once the payments cover the amount, the
job is completed into its sale without a payment of its own (``make_sale``), and the checkout records each payment on it.
"""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.commerce.models import Checkout
from apps.tenancy.permissions import has_business_permission

from .models import CyberJob
from .services import complete_job, create_job, job_number


class _Rehearsal(Exception):
    """Rolls back the rehearsed job and sale."""


def customer_in(organization, customer_id):
    if not customer_id:
        return None
    customer = get_user_model().objects.filter(customer_profiles__organization_id=organization.pk, pk=customer_id).first()
    if not customer:
        raise ValidationError("Choose a customer in this business.")
    return customer


def _job(basket, *, user, customer, number):
    if basket.get("job_id"):
        job = CyberJob.objects.select_for_update().get(pk=basket["job_id"])
        if job.status in ("COMPLETED", "CANCELLED") or job.sale_id:
            raise ValidationError(f"Job {job.number} is already {job.get_status_display().lower()}.")
        if customer and job.customer_id != customer.pk:
            job.customer = customer
            job.save(update_fields=["customer", "updated_at"])
        return job
    return create_job(user=user, lines=basket["lines"], customer=customer, walk_in_customer_name=basket.get("customer_name", ""),
                      allow_price_change=True, number=number)


def make_sale(checkout):
    """The paid checkout's job completed into its sale, with no payment: the checkout records its own."""
    job = _job(checkout.basket, user=checkout.cashier, customer=checkout.customer, number=checkout.number)
    return complete_job(job=job, user=checkout.cashier, payment_method=None, due_date=checkout.basket.get("due_date") or None)


def _charge(*, user, store, key, basket, customer):
    existing = Checkout.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    number = job_number()
    try:
        with transaction.atomic():
            total = complete_job(job=_job(basket, user=user, customer=customer, number=number), user=user, payment_method=None).total
            raise _Rehearsal()
    except _Rehearsal:
        pass
    return Checkout.objects.create(kind=Checkout.CYBER, number=number, branch=store, cashier=user, customer=customer, basket=basket,
                                   total=total, idempotency_key=key)


@transaction.atomic
def charge_visit(*, user, store, key, lines, customer=None, customer_name=""):
    """Services just done for a customer, waiting for payment. No job exists until it is paid."""
    return _charge(user=user, store=store, key=f"cyber-visit:{key}", customer=customer,
                   basket={"lines": lines, "customer_name": customer_name.strip()[:160]})


@transaction.atomic
def charge_job(*, user, store, key, job, customer=None):
    """A job from the desk, done and waiting for payment. One checkout at a time per job."""
    if not has_business_permission(user, "cyber.complete_cyber_job"):
        raise PermissionDenied("Cyber checkout permission required.")
    job = CyberJob.objects.select_for_update().get(pk=job.pk)
    waiting = Checkout.objects.filter(kind=Checkout.CYBER, basket__job_id=job.pk, status__in=Checkout.OPEN).first()
    if waiting:
        return waiting
    lines = [{"service": line.service_name, "quantity": str(line.quantity)} for line in job.lines.all()]
    return _charge(user=user, store=store, key=f"cyber-job:{key or uuid4().hex}", customer=customer or job.customer,
                   basket={"job_id": job.pk, "job_number": job.number, "lines": lines})
