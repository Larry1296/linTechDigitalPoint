from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import Store, TimeStamped


class MpesaOutlet(TimeStamped):
    store = models.ForeignKey(Store, related_name="mpesa_outlets", on_delete=models.PROTECT)
    display_name = models.CharField(max_length=160)
    agent_reference = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.display_name


class MpesaSession(TimeStamped):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    outlet = models.ForeignKey(MpesaOutlet, related_name="sessions", on_delete=models.PROTECT)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="mpesa_sessions", on_delete=models.PROTECT)
    opening_cash = models.DecimalField(max_digits=14, decimal_places=2)
    opening_float = models.DecimalField(max_digits=14, decimal_places=2)
    opened_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=[(OPEN, "Open"), (CLOSED, "Closed")], default=OPEN)
    closing_cash_actual = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    closing_float_actual = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="mpesa_sessions_closed", on_delete=models.PROTECT
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["outlet"], condition=Q(status="OPEN"), name="one_open_mpesa_session_per_outlet"
            ),
            models.CheckConstraint(
                condition=Q(opening_cash__gte=0) & Q(opening_float__gte=0), name="nonnegative_mpesa_opening_balances"
            ),
        ]


class MpesaTransaction(models.Model):
    TYPES = [
        (value, value.replace("_", " ").title())
        for value in [
            "CUSTOMER_DEPOSIT",
            "CUSTOMER_WITHDRAWAL",
            "FLOAT_TOPUP",
            "CASH_REBALANCE",
            "REVERSAL",
            "ADJUSTMENT",
        ]
    ]
    POSTED = "POSTED"
    internal_reference = models.CharField(max_length=60, unique=True)
    idempotency_key = models.CharField(max_length=100, unique=True)
    outlet = models.ForeignKey(MpesaOutlet, related_name="transactions", on_delete=models.PROTECT)
    session = models.ForeignKey(MpesaSession, related_name="transactions", on_delete=models.PROTECT)
    transaction_type = models.CharField(max_length=24, choices=TYPES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    cash_delta = models.DecimalField(max_digits=14, decimal_places=2)
    float_delta = models.DecimalField(max_digits=14, decimal_places=2)
    provider_reference = models.CharField(max_length=100, null=True, blank=True, unique=True)
    customer_reference = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=12, default=POSTED)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, related_name="reversal", on_delete=models.PROTECT
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="mpesa_transactions", on_delete=models.PROTECT
    )
    occurred_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="positive_mpesa_transaction_amount")]
        permissions = [("reverse_mpesa_transaction", "Can reverse M-Pesa agency transactions")]


class MpesaCommissionEntry(TimeStamped):
    outlet = models.ForeignKey(MpesaOutlet, related_name="commissions", on_delete=models.PROTECT)
    period = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)
    settlement_method = models.CharField(max_length=40)
    recognized_at = models.DateTimeField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gte=0), name="nonnegative_mpesa_commission")]


class MpesaReconciliation(models.Model):
    session = models.OneToOneField(MpesaSession, related_name="reconciliation", on_delete=models.PROTECT)
    expected_cash = models.DecimalField(max_digits=14, decimal_places=2)
    actual_cash = models.DecimalField(max_digits=14, decimal_places=2)
    cash_variance = models.DecimalField(max_digits=14, decimal_places=2)
    expected_float = models.DecimalField(max_digits=14, decimal_places=2)
    actual_float = models.DecimalField(max_digits=14, decimal_places=2)
    float_variance = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField(blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="mpesa_reconciliations", on_delete=models.PROTECT)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="mpesa_reconciliations_reviewed", on_delete=models.PROTECT
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
