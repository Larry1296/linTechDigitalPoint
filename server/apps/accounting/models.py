from apps.tenancy.base import TenantModel
"""Internal operating books. Posted records are append-only; corrections reverse them."""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone


class BusinessUnit(models.TextChoices):
    SHOP = 'SHOP', 'Retail Shop'
    CYBER = 'CYBER', 'Cyber Services'
    MPESA = 'MPESA', 'M-Pesa Agency'


class PostedRecord(TenantModel):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"
    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Posted records cannot be edited. Record a reversal with a reason.')
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValidationError('Posted records cannot be deleted.')


class ExpenseCategory(TenantModel):
    name = models.CharField(max_length=120)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="acco_expensecategory_name_org")]


class CashAccount(TenantModel):
    name = models.CharField(max_length=120)
    business_unit = models.CharField(max_length=5, choices=BusinessUnit.choices)
    payment_method = models.CharField(max_length=20)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'business_unit', 'payment_method'], name='unit_payment_account')]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [*constraints, models.UniqueConstraint(fields=["organization", "name"], name="acco_cashaccount_name_org")]


class FinancialPeriod(TenantModel):
    start = models.DateField()
    end = models.DateField()
    closed = models.BooleanField(default=False)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(end__gte=models.F('start')), name='ordered_financial_period')]
        base_manager_name = "objects"
        default_manager_name = "objects"


class CashEntry(PostedRecord):
    branch = models.ForeignKey("core.Store", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    account = models.ForeignKey(CashAccount, on_delete=models.PROTECT)
    business_unit = models.CharField(max_length=5, choices=BusinessUnit.choices)
    occurred_at = models.DateTimeField(default=timezone.now)
    kind = models.CharField(max_length=20, choices=[(x, x) for x in ['INCOME', 'EXPENSE', 'PURCHASE', 'PRINCIPAL', 'OPENING', 'LOAN', 'INVESTMENT']])
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    cogs = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    reference = models.CharField(max_length=160)
    source_key = models.CharField(max_length=180)
    reason = models.TextField(blank=True)
    reversal_of = models.OneToOneField('self', null=True, blank=True, related_name='reversal', on_delete=models.PROTECT)
    class Meta:
        ordering = ['-occurred_at', '-pk']
        permissions = [('view_profit', 'Can view buying costs and profit'), ('reverse_cashentry', 'Can reverse financial entries')]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "source_key"], name="acco_cashentry_source_key_org")]


class Expense(PostedRecord):
    """An operating cost in the period it relates to, whether paid at once or owed (accrued)."""
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    business_unit = models.CharField(max_length=5, choices=BusinessUnit.choices)
    # The payment made when the expense was recorded as already paid; unpaid expenses have none.
    entry = models.OneToOneField(CashEntry, null=True, blank=True, on_delete=models.PROTECT)
    description = models.TextField()
    branch = models.ForeignKey("core.Store", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    incurred_on = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=120, null=True, blank=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class Supplier(TenantModel):
    name = models.CharField(max_length=180)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="acco_supplier_name_org")]


class SupplierPurchase(PostedRecord):
    supplier = models.ForeignKey(Supplier, null=True, on_delete=models.PROTECT)
    receipt = models.OneToOneField('inventory.StockReceipt', related_name='purchase', on_delete=models.PROTECT)
    business_unit = models.CharField(max_length=5, choices=BusinessUnit.choices, default=BusinessUnit.SHOP)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_source = models.CharField(max_length=120, default='UNCONFIRMED')
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class ExpensePayment(PostedRecord):
    """Settles an unpaid (accrued) expense; it is not a second expense."""
    expense = models.ForeignKey(Expense, related_name='payments', on_delete=models.PROTECT)
    entry = models.OneToOneField(CashEntry, on_delete=models.PROTECT)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class PurchasePayment(PostedRecord):
    purchase = models.ForeignKey(SupplierPurchase, related_name='payments', on_delete=models.PROTECT)
    entry = models.OneToOneField(CashEntry, on_delete=models.PROTECT)
    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"


class DailyClosing(PostedRecord):
    date = models.DateField()
    account = models.ForeignKey(CashAccount, on_delete=models.PROTECT)
    expected = models.DecimalField(max_digits=16, decimal_places=2)
    actual = models.DecimalField(max_digits=16, decimal_places=2)
    discrepancy = models.DecimalField(max_digits=16, decimal_places=2)
    reason = models.TextField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['date', 'account'], name='one_daily_account_closing')]
        base_manager_name = "objects"
        default_manager_name = "objects"


class LedgerAccount(TenantModel):
    """A business-local chart, with stable codes used by the posting policy."""
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=[(v, v.title()) for v in ['ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'COGS', 'EXPENSE']])
    is_cash = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'code'], name='ledger_account_business_code')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class JournalEntry(PostedRecord):
    branch = models.ForeignKey('core.Store', on_delete=models.PROTECT)
    posting_date = models.DateField()
    currency = models.CharField(max_length=3)
    source_key = models.CharField(max_length=180)
    description = models.CharField(max_length=240)
    fingerprint = models.CharField(max_length=64, editable=False)
    reversal_of = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='reversal')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'source_key'], name='journal_business_source')]
        indexes = [models.Index(fields=['organization', 'branch', 'posting_date'], name='journal_business_branch_date')]
        permissions = [('post_manual_journal', 'Can post manual journals'), ('reverse_journal', 'Can reverse manual journals')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'
        ordering = ['-posting_date', '-pk']


class JournalLine(PostedRecord):
    entry = models.ForeignKey(JournalEntry, related_name='lines', on_delete=models.PROTECT)
    account = models.ForeignKey(LedgerAccount, related_name='lines', on_delete=models.PROTECT)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)), name='journal_line_one_positive_side')]
        indexes = [models.Index(fields=['organization', 'account', 'entry'], name='journal_account_entry')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class Loan(TenantModel):
    """Money lent to someone, to be paid back by an agreed date. It is owed to the business, never an expense."""
    borrower_name = models.CharField(max_length=120)
    borrower_phone = models.CharField(max_length=30, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=20)  # how the money was handed over: CASH, MPESA, BANK or OTHER
    lent_on = models.DateField()
    due_date = models.DateField()
    notes = models.TextField(blank=True)
    entry = models.OneToOneField(CashEntry, related_name='loan', on_delete=models.PROTECT)
    branch = models.ForeignKey('core.Store', null=True, blank=True, on_delete=models.PROTECT, editable=False)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    class Meta:
        ordering = ['-lent_on', '-pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'idempotency_key'], name='acco_loan_idempotency_org'),
                       models.CheckConstraint(condition=Q(amount__gt=0), name='acco_loan_positive_amount')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class LoanRepayment(TenantModel):
    """Money paid back towards a loan, confirmed as received when recorded."""
    loan = models.ForeignKey(Loan, related_name='repayments', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=20)
    reference = models.CharField(max_length=120, blank=True)  # e.g. the M-Pesa code, required for M-Pesa
    received_on = models.DateField()
    entry = models.OneToOneField(CashEntry, related_name='loan_repayment', on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)
    class Meta:
        ordering = ['received_on', 'pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'idempotency_key'], name='acco_loanrepayment_idempotency_org'),
                       models.CheckConstraint(condition=Q(amount__gt=0), name='acco_loanrepayment_positive_amount')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class MoneyCheck(TenantModel):
    """Money actually counted in one place (cash drawer, M-Pesa, bank) next to what the app expected there.

    It records the comparison only; the books are corrected by recording whatever was missed (a sale, an
    expense), never by forcing the balance to match.
    """
    branch = models.ForeignKey('core.Store', null=True, blank=True, on_delete=models.PROTECT, editable=False)
    method = models.CharField(max_length=20)
    # With a separate cash drawer for each part of the business: whose drawer was counted ("" for a shared place).
    business_unit = models.CharField(max_length=20, choices=BusinessUnit.choices, blank=True, default="")
    expected = models.DecimalField(max_digits=16, decimal_places=2)
    actual = models.DecimalField(max_digits=16, decimal_places=2)
    difference = models.DecimalField(max_digits=16, decimal_places=2)
    cash_count = models.JSONField(default=dict, blank=True)  # notes and coins when counting the drawer
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        ordering = ['-created_at', '-pk']
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class Investment(TenantModel):
    """An account where spare money is kept to earn interest, such as a money market fund (MMF)."""
    name = models.CharField(max_length=120)  # e.g. "Sanlam MMF"
    account_number = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    # Withholding tax taken from the interest before it is added (15% on Kenyan money market funds).
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=15)
    # The published fund whose rate the app keeps up to date by itself (see fund_rates.py), e.g. CIC_MMF_KES; empty when
    # the owner records the rate by hand.
    fund = models.CharField(max_length=40, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'name'], name='acco_investment_name_org')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class InvestmentMovement(TenantModel):
    """Money put into or taken out of an investment, or interest and fees shown on its statement."""
    DEPOSIT, WITHDRAWAL, INTEREST, FEE = 'DEPOSIT', 'WITHDRAWAL', 'INTEREST', 'FEE'
    investment = models.ForeignKey(Investment, related_name='movements', on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[(x, x.title()) for x in [DEPOSIT, WITHDRAWAL, INTEREST, FEE]])
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    occurred_on = models.DateField()
    # Where the money came from or went to: CASH, MPESA, BANK, OTHER, AGENCY_CASH or AGENCY_FLOAT. Empty for interest and fees.
    source = models.CharField(max_length=20, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)
    statement_balance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)  # when worked out from a statement
    entry = models.OneToOneField(CashEntry, null=True, blank=True, related_name='investment_movement', on_delete=models.PROTECT)
    agency_transaction = models.OneToOneField('mpesa.MpesaTransaction', null=True, blank=True, related_name='investment_movement', on_delete=models.PROTECT)
    # The stock purchase a withdrawal paid for, when money was taken out to pay a supplier.
    purchase = models.ForeignKey(SupplierPurchase, null=True, blank=True, related_name='investment_withdrawals', on_delete=models.PROTECT)
    branch = models.ForeignKey('core.Store', null=True, blank=True, on_delete=models.PROTECT, editable=False)
    idempotency_key = models.CharField(max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reverse_reason = models.TextField(blank=True)
    class Meta:
        ordering = ['occurred_on', 'pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'idempotency_key'], name='acco_investmentmovement_idempotency_org'),
                       models.CheckConstraint(condition=Q(amount__gt=0), name='acco_investmentmovement_positive_amount')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class InvestmentRate(TenantModel):
    """The yearly interest rate the fund quotes, recorded once a month; it is what interest estimates are worked out from."""
    investment = models.ForeignKey(Investment, related_name='rates', on_delete=models.PROTECT)
    month = models.DateField()  # the first day of the month the rate applies to
    annual_rate = models.DecimalField(max_digits=6, decimal_places=3)  # % a year, e.g. 13.250
    statement_balance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)  # the balance seen at the same check
    recorded_on = models.DateField()
    note = models.TextField(blank=True)
    # Written by the app from the fund's published rate rather than typed in by a person.
    automatic = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        ordering = ['-month', '-pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'investment', 'month'], name='acco_investmentrate_month_org'),
                       models.CheckConstraint(condition=Q(annual_rate__gte=0, annual_rate__lte=100), name='acco_investmentrate_sensible')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'


class NetWorthSnapshot(TenantModel):
    """The business's net worth as it stood on one day, kept so it can be followed over time (see net_worth.py)."""
    date = models.DateField()
    owns = models.DecimalField(max_digits=16, decimal_places=2)
    owes = models.DecimalField(max_digits=16, decimal_places=2)
    net_worth = models.DecimalField(max_digits=16, decimal_places=2)
    breakdown = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ['date']
        constraints = [models.UniqueConstraint(fields=['organization', 'date'], name='acco_networthsnapshot_date_org')]
        base_manager_name = 'objects'
        default_manager_name = 'objects'
