from apps.tenancy.transactions import lock_business
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.core.models import AuditLog
from .models import CashAccount, CashEntry, DailyClosing, Expense, FinancialPeriod, Supplier, SupplierPurchase


def audit(entry, user, reason, before=None):
    AuditLog.objects.create(action='BOOKS_POSTED', object_type=type(entry).__name__, object_id=str(entry.pk), user=user,
        before=before or {}, after={'reason': reason, 'amount': str(getattr(entry, 'amount', '')), 'id': entry.pk})


def check_date(date, account=None):
    if FinancialPeriod.objects.filter(start__lte=date, end__gte=date, closed=True).exists():
        raise ValidationError('This financial period is closed.')
    if account and DailyClosing.objects.filter(account=account, date__gte=date).exists():
        raise ValidationError('This account has been closed for this date. Post a correction in an open day.')


@transaction.atomic
def post(*, unit, method, amount, kind, reference, key, user=None, cogs=0, occurred_at=None, reason='', reversal_of=None, branch=None, journal=True):
    """A cash-book entry (money in or out). ``journal=False`` when the caller posts the double entry itself."""
    lock_business()
    existing = CashEntry.objects.filter(source_key=key).first()
    if existing:
        if (existing.business_unit, existing.account.payment_method, existing.amount, existing.kind, existing.reference) != (unit, method, Decimal(str(amount)), kind, reference):
            raise ValidationError('This request key was already used for different transaction details.')
        return existing
    account, _ = CashAccount.objects.get_or_create(business_unit=unit, payment_method=method,
        defaults={'name': f'{unit} {method}'})
    account = CashAccount.objects.select_for_update().get(pk=account.pk)
    occurred_at = occurred_at or timezone.now()
    check_date(timezone.localtime(occurred_at).date(), account)
    entry = CashEntry.objects.create(account=account, business_unit=unit, amount=amount, kind=kind, reference=reference,
        source_key=key, created_by=user, branch=branch, cogs=cogs, occurred_at=occurred_at, reason=reason, reversal_of=reversal_of)
    if journal:
        from .ledger import post_cash_entry
        post_cash_entry(entry)
    audit(entry, user, reason, {'reverses': reversal_of.pk, 'amount': str(reversal_of.amount)} if reversal_of else {})
    return entry


def expense_paid(expense):
    """Money paid towards an expense so far (reversed payments count back)."""
    from django.db.models import Q
    from .models import ExpensePayment
    entries = set(ExpensePayment.objects.filter(expense=expense).values_list('entry_id', flat=True))
    if expense.entry_id:
        entries.add(expense.entry_id)
    total = CashEntry.objects.filter(Q(pk__in=entries) | Q(reversal_of_id__in=entries)).aggregate(v=Sum('amount'))['v'] or Decimal('0')
    return -total


def expense_outstanding(expense):
    from apps.accounting.models import JournalEntry
    if JournalEntry.objects.filter(source_key=f'expense-cancel:{expense.pk}').exists():
        return Decimal('0')
    return expense.amount - expense_paid(expense)


@transaction.atomic
def record_expense(*, user, category, unit, method, amount, description, key, paid=True, incurred_on=None, due_date=None):
    """An operating expense in the period it relates to (``incurred_on``), paid now or owed.

    The cost is always booked as Dr expense category / Cr accrued expenses on the incurred date;
    a payment then moves it out of accrued expenses: Dr accrued expenses / Cr cash. So an expense is
    counted once in profit whether it is paid today, later, or in instalments.
    """
    from .ledger import expense_account, paired, post_journal, resolve_branch
    lock_business()
    existing = Expense.objects.filter(idempotency_key=key).first()
    if existing:
        if (existing.amount, existing.category_id, existing.description) != (Decimal(str(amount)).quantize(Decimal('0.01')), category.pk, description):
            raise ValidationError('This request key was already used for different expense details.')
        return existing
    amount = Decimal(str(amount))
    if not amount.is_finite() or amount <= 0:
        raise ValidationError('Expense amount must be positive.')
    amount = amount.quantize(Decimal('0.01'))
    incurred_on = incurred_on or timezone.localdate()
    branch = resolve_branch()
    entry = None
    if paid:
        entry = post(unit=unit, method=method, amount=-amount, kind='EXPENSE', reference=description[:160],
                     key=f'expense:{key}', user=user, reason=description, branch=branch, journal=False)
    expense = Expense.objects.create(category=category, business_unit=unit, description=description, created_by=user,
                                     entry=entry, amount=amount, incurred_on=incurred_on, due_date=due_date, branch=branch, idempotency_key=key)
    post_journal(key=f'expense:{expense.pk}', description=f'{category.name}: {description}'[:240], branch=branch, date=incurred_on,
                 user=user, lines=paired(expense_account(category), '2150', amount))
    if entry:
        _post_expense_payment(expense, entry, user)
    audit(expense, user, description)
    return expense


def _post_expense_payment(expense, entry, user):
    from .ledger import cash_code, paired, post_journal
    from .models import ExpensePayment
    post_journal(key=f'cash:{entry.pk}', description=f'Paid: {expense.description}'[:240], branch=expense.branch_id,
                 date=timezone.localtime(entry.occurred_at).date(), user=user,
                 lines=paired('2150', cash_code(entry.account.payment_method), -entry.amount))
    ExpensePayment.objects.create(expense=expense, entry=entry, created_by=user)


@transaction.atomic
def pay_expense(*, expense, amount, method, key, user):
    """Pays an owed expense (or part of it). This settles a liability; it is not a second expense."""
    lock_business()
    existing = CashEntry.objects.filter(source_key=f'expense-payment:{key}').first()
    if existing:
        return existing
    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    if amount <= 0:
        raise ValidationError('Enter a payment above zero.')
    if amount > expense_outstanding(expense):
        raise ValidationError('Payment exceeds what is still owed for this expense.')
    entry = post(unit=expense.business_unit, method=method, amount=-amount, kind='EXPENSE', reference=f'Paid: {expense.description}'[:160],
                 key=f'expense-payment:{key}', user=user, branch=expense.branch, journal=False)
    _post_expense_payment(expense, entry, user)
    return entry


@transaction.atomic
def cancel_expense(*, expense, user, reason):
    """Removes a wrongly recorded expense from the books: reverses its cost and any payments made."""
    from .ledger import reverse_journal
    from .models import ExpensePayment, JournalEntry
    lock_business()
    if not reason.strip():
        raise ValidationError('Explain why the expense is being cancelled.')
    accrual = JournalEntry.objects.filter(source_key=f'expense:{expense.pk}').first()
    if accrual and not JournalEntry.objects.filter(reversal_of=accrual).exists():
        reverse_journal(accrual, user=user, reason=reason, key=f'expense-cancel:{expense.pk}')
    payments = list(ExpensePayment.objects.filter(expense=expense).values_list('entry_id', flat=True))
    if expense.entry_id and expense.entry_id not in payments:
        payments.append(expense.entry_id)
    for entry in CashEntry.objects.filter(pk__in=payments):
        if not CashEntry.objects.filter(reversal_of=entry).exists():
            reverse(entry=entry, user=user, reason=reason)
    return expense


@transaction.atomic
def reverse(*, entry, user, reason, allow_loan=False, allow_investment=False):
    lock_business()
    entry = CashEntry.objects.select_for_update().get(pk=entry.pk)
    if not reason.strip():
        raise ValidationError('A correction reason is required.')
    if entry.reversal_of_id or CashEntry.objects.filter(reversal_of=entry).exists():
        raise ValidationError('This entry has already been reversed or is a reversal.')
    if entry.kind == 'PRINCIPAL':
        raise ValidationError('Reverse agency principal from the M-Pesa desk so cash and float stay in sync.')
    # These cash entries are one side of a larger journal; reversing only the cash would leave the books disagreeing.
    if entry.source_key.startswith('refund:'):
        raise ValidationError('Correct a customer refund from the sale it belongs to, not from the cash book.')
    if entry.kind == 'LOAN' and not allow_loan:
        raise ValidationError('Correct money lent or repaid from the Money lent page, not from the cash book.')
    if entry.kind == 'INVESTMENT' and not allow_investment:
        raise ValidationError('Correct money put into or taken out of an investment from the Investments page, not from the cash book.')
    if entry.source_key.startswith('landed:'):
        raise ValidationError('Correct delivery costs through a stock receipt correction, not from the cash book.')
    reversal = post(unit=entry.business_unit, method=entry.account.payment_method, amount=-entry.amount, cogs=-entry.cogs,
        kind=entry.kind, reference=entry.reference, key=f'reversal:{entry.pk}', user=user, reason=reason, reversal_of=entry, branch=entry.branch)
    if entry.source_key.startswith('payment:'):
        # A customer payment that did not really happen: the customer owes the amount again.
        from apps.commerce.models import Payment
        from .ledger import reverse_journal
        from .models import JournalEntry
        payment = Payment.objects.filter(pk=entry.source_key.split(':', 1)[1]).first()
        journal = JournalEntry.objects.filter(source_key=entry.source_key).first()
        if journal and not JournalEntry.objects.filter(reversal_of=journal).exists():
            reverse_journal(journal, user=user, reason=reason, key=f'payment-reversal:{payment.pk if payment else entry.pk}')
        if payment and payment.status == 'COMPLETED':
            Payment.objects.filter(pk=payment.pk).update(status='REVERSED')
    if entry.source_key.startswith('commission:'):
        # Commission that was not really earned: its revenue (and anything Safaricom was said to owe) comes out with the cash.
        from apps.mpesa.commission import _reverse_journals, mark_undone
        from apps.mpesa.models import MpesaCommissionEntry
        commission = MpesaCommissionEntry.objects.filter(pk=entry.source_key.split(':', 1)[1]).first()
        if commission:
            _reverse_journals(commission, user, reason)
            mark_undone(commission, reason)
    # Reversing the payment an expense was recorded with means the expense itself was wrong (e.g. a
    # duplicate): its cost is reversed too. Reversing a later payment only makes the bill unpaid again.
    expense = Expense.objects.filter(entry=entry).first()
    if expense:
        from .ledger import reverse_journal
        from .models import JournalEntry
        accrual = JournalEntry.objects.filter(source_key=f'expense:{expense.pk}').first()
        if accrual and not JournalEntry.objects.filter(reversal_of=accrual).exists():
            reverse_journal(accrual, user=user, reason=reason, key=f'expense-cancel:{expense.pk}')
    return reversal


@transaction.atomic
def link_receipt(receipt):
    """The supplier purchase behind a stock receipt: what is owed for the goods and billed delivery."""
    lock_business()
    supplier = None
    if receipt.supplier_name:
        supplier, _ = Supplier.objects.get_or_create(name=receipt.supplier_name)
    goods = sum((line.received_quantity * line.unit_cost for line in receipt.lines.all() if not line.uncosted), Decimal('0'))
    billed = sum((Decimal(c['amount']) for c in receipt.landed_costs if c['paid_by'] == 'SUPPLIER_INVOICE'), Decimal('0'))
    purchase, _ = SupplierPurchase.objects.get_or_create(receipt=receipt, defaults={
        'supplier': supplier, 'created_by': receipt.created_by, 'amount': (goods + billed).quantize(Decimal('0.01'))})
    from .ledger import post_purchase
    landed_paid = [(c['paid_by'], Decimal(c['amount'])) for c in receipt.landed_costs if c['paid_by'] != 'SUPPLIER_INVOICE']
    post_purchase(purchase, landed_paid=landed_paid)
    for method, amount in landed_paid:
        # Money paid out now (e.g. a transporter paid in cash) appears in the cash book; its journal is above.
        post(unit='SHOP', method=method, amount=-amount, kind='PURCHASE', reference=f'Delivery for {receipt.receipt_number}',
             key=f'landed:{receipt.pk}:{method}:{amount}', user=receipt.created_by, occurred_at=receipt.received_at,
             branch=receipt.branch, journal=False)
    return purchase


def purchase_outstanding(purchase):
    """What is still owed to the supplier: purchase − returns − payments (reversed payments count back).
    Nothing for a receipt marked as stock the business already owned: it was never bought."""
    from django.db.models import Q
    from apps.inventory.models import PurchaseReturn, StockReceipt
    if purchase.receipt.document_status == StockReceipt.OPENING_BALANCE:
        return Decimal('0')
    paid = -(CashEntry.objects.filter(Q(purchasepayment__purchase=purchase) | Q(reversal_of__purchasepayment__purchase=purchase))
             .aggregate(v=Sum('amount'))['v'] or Decimal('0'))
    returned = PurchaseReturn.objects.filter(receipt=purchase.receipt).aggregate(v=Sum('total_cost'))['v'] or Decimal('0')
    return purchase.amount - returned - paid


@transaction.atomic
def pay_purchase(*, purchase, amount, method, key, user, reference='', occurred_at=None):
    """Settles what is owed to a supplier. It is not an expense and does not touch inventory."""
    from .models import PurchasePayment
    lock_business()
    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    if amount <= 0:
        raise ValidationError('Enter a payment above zero.')
    existing = CashEntry.objects.filter(source_key=f'purchase:{key}').first()
    if existing:
        if existing.amount != -amount or existing.account.payment_method != method or not PurchasePayment.objects.filter(purchase=purchase, entry=existing).exists():
            raise ValidationError('Payment key already used.')
        return existing
    if amount > purchase_outstanding(purchase):
        raise ValidationError('Payment exceeds what is still owed to the supplier for this receipt.')
    entry = post(unit=purchase.business_unit, method=method, amount=-amount, kind='PURCHASE',
                 reference=(reference or purchase.receipt.receipt_number)[:160], key=f'purchase:{key}', user=user,
                 branch=purchase.receipt.branch, occurred_at=occurred_at)
    PurchasePayment.objects.create(purchase=purchase, entry=entry, created_by=user)
    return entry


@transaction.atomic
def close_day(*, account, date, actual, reason, user):
    lock_business()
    account = CashAccount.objects.select_for_update().get(pk=account.pk)
    check_date(date, account)
    if date > timezone.localdate():
        raise ValidationError('Cannot close a future day.')
    expected = CashEntry.objects.filter(account=account, occurred_at__date__lte=date).aggregate(v=Sum('amount'))['v'] or Decimal('0')
    discrepancy = actual - expected
    if discrepancy and not reason.strip():
        raise ValidationError('Explain the closing discrepancy.')
    closing = DailyClosing.objects.create(account=account, date=date, actual=actual, expected=expected,
        discrepancy=discrepancy, reason=reason, created_by=user)
    audit(closing, user, reason, {'expected': str(expected), 'actual': str(actual)})
    return closing
