"""M-KOPA phones sold as a dealer.

M-KOPA owns the phones until a customer pays them off: the dealer holds them, sells each on one of M-KOPA's plans (a
deposit, then so much a day for so many days, paid by the customer to M-KOPA) and earns a commission for each phone
sold. So the phones are never the business's stock and the customer's money never passes through its books; the only
money that is the business's is the commission M-KOPA pays, which counts as profit when it is paid.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.tenancy.base import TenantModel


class MkopaPhone(TenantModel):
    """A phone model M-KOPA gives the dealer to sell, such as X30."""
    name = models.CharField(max_length=80)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="mkopa_phone_name_org")]
        base_manager_name = "objects"
        default_manager_name = "objects"

    def __str__(self):
        return self.name


class MkopaPlan(TenantModel):
    """One way a customer can pay for a phone: a deposit, then ``daily_payment`` a day for ``days`` days. The dealer's
    commission for each phone sold on it is ``commission``. A sale keeps the terms it was made on, so changing a plan
    later never changes what earlier sales earned."""
    phone = models.ForeignKey(MkopaPhone, related_name="plans", on_delete=models.PROTECT)
    deposit = models.DecimalField(max_digits=12, decimal_places=2)
    daily_payment = models.DecimalField(max_digits=12, decimal_places=2)
    days = models.PositiveIntegerField()
    # The commission per phone the owner typed (None: left for the app to learn), and the one the app learned from
    # M-KOPA's payments (None until a payment pins it down). The learned one is used once known.
    commission = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    learned_commission = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    learned_from = models.PositiveIntegerField(default=0)  # how many payments included phones sold on this plan
    learned_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    @property
    def rate(self):
        """The commission one phone sold on this plan earns, as best known: learned, else typed, else None."""
        return self.learned_commission if self.learned_commission is not None else self.commission

    class Meta:
        ordering = ["phone", "deposit", "pk"]
        constraints = [models.CheckConstraint(condition=Q(deposit__gte=0) & Q(daily_payment__gt=0) & Q(days__gt=0) & Q(commission__gte=0),
                                              name="mkopa_plan_sensible")]
        base_manager_name = "objects"
        default_manager_name = "objects"


class MkopaStock(TenantModel):
    """Phones M-KOPA handed to the dealer (``quantity`` above zero) or the dealer gave back (below zero)."""
    RECEIVED, RETURNED = "RECEIVED", "RETURNED"
    phone = models.ForeignKey(MkopaPhone, related_name="stock", on_delete=models.PROTECT)
    quantity = models.IntegerField()
    moved_on = models.DateField()
    notes = models.CharField(max_length=300, blank=True)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-moved_on", "-pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "idempotency_key"], name="mkopa_stock_idempotency_org"),
                       models.CheckConstraint(condition=~Q(quantity=0), name="mkopa_stock_not_zero")]
        base_manager_name = "objects"
        default_manager_name = "objects"


class MkopaSale(TenantModel):
    """A phone sold to a customer on a plan, with the plan's terms and commission as they were on the day."""
    phone = models.ForeignKey(MkopaPhone, related_name="sales", on_delete=models.PROTECT)
    plan = models.ForeignKey(MkopaPlan, related_name="sales", on_delete=models.PROTECT)
    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=30, blank=True)
    imei = models.CharField(max_length=30, blank=True)
    sold_on = models.DateField()
    deposit = models.DecimalField(max_digits=12, decimal_places=2)
    daily_payment = models.DecimalField(max_digits=12, decimal_places=2)
    days = models.PositiveIntegerField()
    commission = models.DecimalField(max_digits=12, decimal_places=2)  # what the plan was expected to earn on the day
    notes = models.CharField(max_length=300, blank=True)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)
    # The M-KOPA payment that paid this phone's commission, and the part of that payment that was for it.
    paid_by = models.ForeignKey("MkopaCommission", null=True, blank=True, related_name="sales", on_delete=models.PROTECT)
    commission_received = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-sold_on", "-pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "idempotency_key"], name="mkopa_sale_idempotency_org"),
                       models.UniqueConstraint(fields=["organization", "imei"], condition=~Q(imei="") & Q(reversed_at__isnull=True),
                                               name="mkopa_sale_imei_once")]
        base_manager_name = "objects"
        default_manager_name = "objects"


class MkopaCommission(TenantModel):
    """Commission M-KOPA paid the dealer: income when it arrives, into the place it was paid to."""
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=20)  # where it was paid: CASH, MPESA, BANK or OTHER
    reference = models.CharField(max_length=120, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    entry = models.OneToOneField("accounting.CashEntry", related_name="mkopa_commission", on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-paid_on", "-pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "idempotency_key"], name="mkopa_commission_idempotency_org"),
                       models.CheckConstraint(condition=Q(amount__gt=0), name="mkopa_commission_positive")]
        base_manager_name = "objects"
        default_manager_name = "objects"
