"""A kyama (chama): a savings group the business owner runs, usually as its treasurer.

The kyama's money belongs to its members, not to the shop. Nothing here posts to the shop's cash book or
ledger, so the shop's sales, profit, money check and net worth never include it; the kyama keeps its own
records below. Contributions are owed per period (every day, week or month); a contribution not fully paid by
its deadline (the period date plus the grace days, or the date promised in an excuse) is fined once. Records
are never edited away: a payment or payout made by mistake is reversed, and a fine is waived with a reason.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.tenancy.base import TenantModel

FREQUENCIES = [("DAILY", "Every day"), ("WEEKLY", "Every week"), ("MONTHLY", "Every month")]
PAYOUT_MODES = [("ROTATION", "Members take turns to receive the money"), ("SAVINGS", "Money is saved together, no turns")]
TURN_CHOICES = [("ORDER", "In the order the members are listed"), ("AGREED", "The members agree who receives next, each turn")]
ROLES = [("CHAIRPERSON", "Chairperson"), ("VICE_CHAIRPERSON", "Vice-chairperson"), ("SECRETARY", "Secretary"),
         ("TREASURER", "Treasurer"), ("ORGANISER", "Organising secretary"), ("MEMBER", "Member")]
LEADERSHIP = [role for role, _ in ROLES if role != "MEMBER"]
METHODS = [("CASH", "Cash"), ("MPESA", "M-Pesa"), ("BANK", "Bank"), ("OTHER", "Other")]


class Kyama(TenantModel):
    name = models.CharField(max_length=120)
    contribution_amount = models.DecimalField(max_digits=12, decimal_places=2)
    frequency = models.CharField(max_length=10, choices=FREQUENCIES)
    start_date = models.DateField()  # the first contribution recorded here; later ones follow every day, week or month
    grace_days = models.PositiveSmallIntegerField(default=0)
    fine_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payout_mode = models.CharField(max_length=10, choices=PAYOUT_MODES, default="ROTATION")
    periods_per_round = models.PositiveSmallIntegerField(default=1)  # contributions collected before one member receives
    turn_choice = models.CharField(max_length=10, choices=TURN_CHOICES, default="ORDER")
    # The member the members agreed receives the next turn; cleared once that turn is given out.
    next_receiver = models.ForeignKey("KyamaMember", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    next_receiver_note = models.CharField(max_length=500, blank=True)
    next_receiver_set_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    dues_through = models.DateField(null=True, blank=True)  # contributions are owed (rows exist) up to this period
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [models.CheckConstraint(condition=Q(contribution_amount__gt=0), name="kyama_positive_contribution"),
                       models.CheckConstraint(condition=Q(fine_amount__gte=0), name="kyama_fine_not_negative"),
                       models.CheckConstraint(condition=Q(periods_per_round__gte=1), name="kyama_round_has_periods")]
        base_manager_name = "objects"
        default_manager_name = "objects"

    def __str__(self):
        return self.name


class KyamaMember(TenantModel):
    kyama = models.ForeignKey(Kyama, related_name="members", on_delete=models.PROTECT)
    full_name = models.CharField(max_length=120)
    id_number = models.CharField(max_length=20)
    phone = models.CharField(max_length=20)
    role = models.CharField(max_length=20, choices=ROLES, default="MEMBER")
    turn_position = models.PositiveIntegerField(default=0)  # order in which members receive the money
    joined_on = models.DateField()
    left_on = models.DateField(null=True, blank=True)  # owes nothing from this date
    leave_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["turn_position", "pk"]
        constraints = [models.UniqueConstraint(fields=["kyama", "id_number"], name="kyama_member_unique_id"),
                       models.UniqueConstraint(fields=["kyama", "role"], condition=~Q(role="MEMBER") & Q(left_on__isnull=True),
                                               name="kyama_one_holder_per_office")]
        base_manager_name = "objects"
        default_manager_name = "objects"

    def __str__(self):
        return self.full_name


class KyamaDue(TenantModel):
    """One member's contribution for one period, and the fine if it was not paid in time."""
    kyama = models.ForeignKey(Kyama, related_name="dues", on_delete=models.PROTECT)
    member = models.ForeignKey(KyamaMember, related_name="dues", on_delete=models.PROTECT)
    period_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    deadline = models.DateField()  # period date plus the grace days at the time
    excused_until = models.DateField(null=True, blank=True)  # the member asked to pay late and promised this date
    excuse_reason = models.TextField(blank=True)
    excused_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    excused_at = models.DateTimeField(null=True, blank=True)
    fine_checked = models.BooleanField(default=False)  # the deadline passed and the fine rule was applied once
    fine_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fined_on = models.DateField(null=True, blank=True)
    fine_waived_at = models.DateTimeField(null=True, blank=True)
    fine_waive_reason = models.TextField(blank=True)
    fine_waived_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["period_date", "member__turn_position", "pk"]
        constraints = [models.UniqueConstraint(fields=["member", "period_date"], name="kyama_one_due_per_period")]
        base_manager_name = "objects"
        default_manager_name = "objects"

    @property
    def pay_by(self):
        return self.excused_until or self.deadline


class KyamaPayment(TenantModel):
    """Money a member handed to the treasurer: shared out to their oldest contributions, then fines, then ahead."""
    kyama = models.ForeignKey(Kyama, related_name="payments", on_delete=models.PROTECT)
    member = models.ForeignKey(KyamaMember, related_name="payments", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=10, choices=METHODS)
    reference = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-paid_on", "-pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "idempotency_key"], name="kyama_payment_idempotency"),
                       models.CheckConstraint(condition=Q(amount__gt=0), name="kyama_payment_positive")]
        base_manager_name = "objects"
        default_manager_name = "objects"


class KyamaAllocation(TenantModel):
    PARTS = [("CONTRIBUTION", "Contribution"), ("FINE", "Fine")]
    payment = models.ForeignKey(KyamaPayment, related_name="allocations", on_delete=models.PROTECT)
    due = models.ForeignKey(KyamaDue, related_name="allocations", on_delete=models.PROTECT)
    part = models.CharField(max_length=12, choices=PARTS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["due__period_date", "pk"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="kyama_allocation_positive")]
        base_manager_name = "objects"
        default_manager_name = "objects"


class KyamaPayout(TenantModel):
    """Money the treasurer gave out: a member's turn (round) in a rotating kyama, or a share-out from savings."""
    kyama = models.ForeignKey(Kyama, related_name="payouts", on_delete=models.PROTECT)
    member = models.ForeignKey(KyamaMember, related_name="payouts", on_delete=models.PROTECT)
    round_number = models.PositiveIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=10, choices=METHODS)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)
    reversed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-paid_on", "-pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "idempotency_key"], name="kyama_payout_idempotency"),
                       models.UniqueConstraint(fields=["kyama", "round_number"], condition=Q(reversed_at__isnull=True, round_number__isnull=False),
                                               name="kyama_one_payout_per_round"),
                       models.CheckConstraint(condition=Q(amount__gt=0), name="kyama_payout_positive")]
        base_manager_name = "objects"
        default_manager_name = "objects"
