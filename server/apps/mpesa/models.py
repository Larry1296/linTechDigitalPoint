from apps.tenancy.base import TenantModel
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import Store, TimeStamped


class MpesaOutlet(TimeStamped):
    store = models.ForeignKey(Store, related_name="mpesa_outlets", on_delete=models.PROTECT)
    display_name = models.CharField(max_length=160)
    agent_reference = models.CharField(max_length=80, blank=True)  # the M-Pesa agent number
    store_number = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.display_name
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class MpesaSession(TimeStamped):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    outlet = models.ForeignKey(MpesaOutlet, related_name="sessions", on_delete=models.PROTECT)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="mpesa_sessions", on_delete=models.PROTECT)
    opening_cash = models.DecimalField(max_digits=14, decimal_places=2)
    opening_float = models.DecimalField(max_digits=14, decimal_places=2)
    opened_at = models.DateTimeField()
    # Notes and coins counted when the shift opened: {"1000": 3, "500": 2, ..., "coins": "85.00"}.
    opening_cash_count = models.JSONField(default=dict, blank=True)
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
        base_manager_name = "objects"
        default_manager_name = "objects"


class MpesaTransaction(TenantModel):
    TYPES = [
        (value, value.replace("_", " ").title())
        for value in [
            "CUSTOMER_DEPOSIT",
            "CUSTOMER_WITHDRAWAL",
            "FLOAT_TOPUP",
            "CASH_REBALANCE",
            "REVERSAL",
            "ADJUSTMENT",
            "INVESTMENT",  # owner moving money to or from an investment such as an MMF (Investments page)
            "COMMISSION",  # Safaricom's commission paid into the agency float or cash (Commission page)
        ]
    ]
    POSTED = "POSTED"
    internal_reference = models.CharField(max_length=60)
    idempotency_key = models.CharField(max_length=100)
    outlet = models.ForeignKey(MpesaOutlet, related_name="transactions", on_delete=models.PROTECT)
    session = models.ForeignKey(MpesaSession, related_name="transactions", on_delete=models.PROTECT)
    transaction_type = models.CharField(max_length=24, choices=TYPES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    cash_delta = models.DecimalField(max_digits=14, decimal_places=2)
    float_delta = models.DecimalField(max_digits=14, decimal_places=2)
    provider_reference = models.CharField(max_length=100, null=True, blank=True)
    customer_reference = models.CharField(max_length=40, blank=True)
    # The customer's details for a deposit or withdrawal, taken before the transaction is done on the M-Pesa line.
    customer_name = models.CharField(max_length=120, blank=True)
    customer_phone = models.CharField(max_length=15, blank=True)  # stored as 2547XXXXXXXX / 2541XXXXXXXX
    customer_id_number = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=12, default=POSTED)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, related_name="reversal", on_delete=models.PROTECT
    )
    # A corrected entry points at the one it replaces (which is reversed in the same step).
    corrects = models.OneToOneField("self", null=True, blank=True, related_name="corrected_by", on_delete=models.PROTECT)
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
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [*constraints, models.UniqueConstraint(fields=["organization", "internal_reference"], name="mpes_mpesatransaction_internal_referen_org"), models.UniqueConstraint(fields=["organization", "idempotency_key"], name="mpes_mpesatransaction_idempotency_key_org"), models.UniqueConstraint(fields=["organization", "provider_reference"], name="mpes_mpesatransaction_provider_referen_org")]


class MpesaCommissionEntry(TimeStamped):
    """Commission Safaricom paid for one month's agency work.

    ``period`` is the first day of the month it was earned in and ``recognized_at`` when it was paid. The income
    counts on ``earned_on``: the month's last day, or the day it was paid when that month's books were already closed.
    """
    outlet = models.ForeignKey(MpesaOutlet, related_name="commissions", on_delete=models.PROTECT)
    period = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=100)
    # Where Safaricom's money went: AGENCY_FLOAT or AGENCY_CASH (through the open shift), or MPESA, BANK, CASH, OTHER.
    settlement_method = models.CharField(max_length=40)
    recognized_at = models.DateTimeField()
    earned_on = models.DateField(null=True, blank=True)
    agency_transaction = models.OneToOneField(MpesaTransaction, null=True, blank=True, related_name="commission", on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100, blank=True, default="")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gte=0), name="nonnegative_mpesa_commission")]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [*constraints, models.UniqueConstraint(fields=["organization", "reference"], name="mpes_mpesacommissione_reference_org")]


class MpesaReconciliation(TenantModel):
    session = models.OneToOneField(MpesaSession, related_name="reconciliation", on_delete=models.PROTECT)
    expected_cash = models.DecimalField(max_digits=14, decimal_places=2)
    actual_cash = models.DecimalField(max_digits=14, decimal_places=2)
    cash_variance = models.DecimalField(max_digits=14, decimal_places=2)
    expected_float = models.DecimalField(max_digits=14, decimal_places=2)
    actual_float = models.DecimalField(max_digits=14, decimal_places=2)
    float_variance = models.DecimalField(max_digits=14, decimal_places=2)
    # Notes and coins counted at closing, in the same shape as MpesaSession.opening_cash_count.
    cash_count = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="mpesa_reconciliations", on_delete=models.PROTECT)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="mpesa_reconciliations_reviewed", on_delete=models.PROTECT
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
