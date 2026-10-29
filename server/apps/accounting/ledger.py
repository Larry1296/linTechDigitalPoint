"""Central double-entry posting. All amounts are in the business currency.

Revenue belongs to fulfillment, not payment initiation. Legacy cash books remain
available; the journal starts prospectively and never invents opening balances.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.core.models import Store
from apps.tenancy.context import organization_id, branch_id
from apps.tenancy.models import Organization
from .models import LedgerAccount, JournalEntry, JournalLine
from .services import check_date, audit

CHART = {
    '1000': ('Cash', 'ASSET', True), '1010': ('Bank', 'ASSET', True),
    '1020': ('Mobile money', 'ASSET', True), '1030': ('Other confirmed money', 'ASSET', True),
    '1100': ('Customer balances (receivables)', 'ASSET', False), '1200': ('Stock (inventory)', 'ASSET', False),
    '1250': ('Interbranch stock clearing', 'ASSET', False),
    '1150': ('Money lent out (loans to others)', 'ASSET', False),
    '1160': ('Commission due from Safaricom', 'ASSET', False),
    '1400': ('Investments (e.g. money market funds)', 'ASSET', False),
    '1300': ('Agency cash', 'ASSET', True), '1310': ('Agency electronic float', 'ASSET', True),
    '2000': ('Supplier balances (payables)', 'LIABILITY', False),
    '2100': ('Accrued service costs', 'LIABILITY', False),
    '2150': ('Accrued expenses (unpaid bills)', 'LIABILITY', False),
    '2200': ('Tax payable', 'LIABILITY', False),
    '2300': ('Guest deposits (paid in advance, not yet used)', 'LIABILITY', False),
    '3000': ('Opening equity', 'EQUITY', False),
    '4000': ('Retail sales', 'REVENUE', False), '4010': ('Agency commission', 'REVENUE', False),
    '4020': ('Service revenue', 'REVENUE', False), '4900': ('Other income', 'REVENUE', False),
    '4910': ('Interest earned on investments', 'REVENUE', False),
    '4030': ('Food and drinks made (menu)', 'REVENUE', False), '4040': ('Rooms and guest services', 'REVENUE', False),
    '5000': ('Cost of goods sold (retail)', 'COGS', False),
    '5010': ('Service direct costs (materials and configured cost)', 'COGS', False),
    '5020': ('Food used in the kitchen (cost of meals)', 'COGS', False),
    '6000': ('Operating expenses', 'EXPENSE', False),
    '6100': ('Stock losses and corrections', 'EXPENSE', False),
    '6200': ('Investment fees and losses', 'EXPENSE', False),
}
# Revenue and direct cost accounts by what was sold. Services include Cyber jobs.
REVENUE_ACCOUNT = {'STOCK_ITEM': '4000', 'SERVICE': '4020'}
COST_ACCOUNT = {'STOCK_ITEM': '5000', 'SERVICE': '5010'}
# A guest's deposit used against their bill is paid from what the hotel holds for them, not from a till.
CASH_CODES = {'CASH': '1000', 'BANK': '1010', 'MPESA': '1020', 'OTHER': '1030',
              'CASH_ON_PICKUP': '1000', 'AGENCY_CASH': '1300', 'AGENCY_FLOAT': '1310', 'FLOAT': '1310', 'DEPOSIT': '2300'}


def revenue_account(variant):
    """Where a sold item's revenue goes: a dish from the menu and a room night have their own, so a hotel sees each."""
    from apps.hotel.models import MenuItem, RoomType
    if variant.product.product_type == 'SERVICE':
        if MenuItem.objects.filter(variant_id=variant.pk).exists():
            return '4030'
        if RoomType.objects.filter(variant_id=variant.pk).exists():
            return '4040'
    return REVENUE_ACCOUNT[variant.product.product_type]


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Enter a finite money amount.')


def cash_code(method):
    if method not in CASH_CODES:
        raise ValidationError('Choose a supported confirmed payment method.')
    return CASH_CODES[method]


def resolve_branch(branch=None):
    selected = getattr(branch, 'pk', branch) or branch_id()
    stores = Store.objects.all()
    if selected:
        result = stores.filter(pk=selected).first()
        if result:
            return result
    else:
        candidates = list(stores[:2])
        if len(candidates) == 1:
            return candidates[0]
    raise ValidationError('Select the branch before posting to the ledger.')


@transaction.atomic
def post_journal(*, key, description, lines, branch=None, date=None, user=None, reversal_of=None):
    organization = Organization.objects.select_for_update().get(pk=organization_id())
    branch = resolve_branch(branch)
    date = date or timezone.localdate()
    normalized = []
    for code, debit, credit in lines:
        debit, credit = money(debit), money(credit)
        if debit == credit == 0:
            continue
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise ValidationError('Each journal line needs one positive debit or credit.')
        normalized.append((str(code), str(debit), str(credit)))
    if len(normalized) < 2 or sum(Decimal(d) - Decimal(c) for _, d, c in normalized) != 0:
        raise ValidationError('Journal debits must equal credits and contain at least two lines.')
    fingerprint = hashlib.sha256(json.dumps([branch.pk, str(date), organization.currency, description,
        sorted(normalized), getattr(reversal_of, 'pk', None)], sort_keys=True).encode()).hexdigest()
    existing = JournalEntry.objects.filter(source_key=key).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValidationError('This posting key was already used for different journal details.')
        return existing
    check_date(date)
    accounts = {}
    for code, _, _ in normalized:
        if code in CHART:
            name, kind, is_cash = CHART[code]
            accounts[code], _ = LedgerAccount.objects.get_or_create(code=code, defaults={'name': name, 'kind': kind, 'is_cash': is_cash})
        elif code.startswith('6000-'):
            # One expense account per expense category, so reports show rent, wages, etc. separately.
            from .models import ExpenseCategory
            category = ExpenseCategory.objects.filter(pk=code.split('-', 1)[1]).first()
            if not category:
                raise ValidationError('Unknown expense category account.')
            accounts[code], _ = LedgerAccount.objects.get_or_create(code=code, defaults={'name': category.name, 'kind': 'EXPENSE', 'is_cash': False})
        else:
            accounts[code] = LedgerAccount.objects.filter(code=code).first()
            if not accounts[code]:
                raise ValidationError('Unknown account code.')
    entry = JournalEntry.objects.create(branch=branch, posting_date=date, currency=organization.currency,
        source_key=key, description=description, fingerprint=fingerprint, created_by=user, reversal_of=reversal_of)
    JournalLine.objects.bulk_create([JournalLine(entry=entry, account=accounts[code], debit=d, credit=c,
        created_by=user) for code, d, c in normalized])
    audit(entry, user, description, {'source': key})
    return entry


def paired(debit, credit, amount):
    amount = money(amount)
    return [(debit, amount, 0), (credit, 0, amount)] if amount >= 0 else [(credit, -amount, 0), (debit, 0, -amount)]


def expense_account(category):
    return f'6000-{category.pk}'


def sale_cost_lines(sale):
    """Direct cost lines for a sale, from recorded cost layers only; nothing is estimated from prices."""
    from apps.commerce.models import SaleAllocation
    from apps.inventory.models import Movement
    stock_cost = {'5000': Decimal(0), '5010': Decimal(0)}
    for allocation in SaleAllocation.objects.filter(item__sale=sale).select_related('item__variant__product'):
        stock_cost[COST_ACCOUNT[allocation.item.variant.product.product_type]] += allocation.quantity * allocation.unit_cost
    materials = sum((m.quantity * m.lot.unit_cost for m in Movement.objects.filter(
        reference=sale.number, movement_type='CYBER_CONSUMPTION').select_related('lot')), Decimal(0))
    lines = paired('5000', '1200', money(stock_cost['5000'])) + paired('5010', '1200', money(stock_cost['5010'] + materials))
    # A configured direct service cost (no measurable materials) is accrued, never fabricated as cash paid.
    configured = money(sum((item.cost for item in sale.items.filter(variant__product__product_type='SERVICE')), Decimal(0))) - money(materials + stock_cost['5010'])
    if configured > 0:
        lines += paired('5010', '2100', configured)
    return lines


def post_sale(sale):
    """Revenue when delivered: the customer owes the payable total; tax is owed to the tax authority."""
    if not sale.total and not sale.cogs:
        return None
    revenue = {}
    for item in sale.items.select_related('variant__product'):
        account = revenue_account(item.variant)
        revenue[account] = revenue.get(account, Decimal(0)) + item.net_amount
    lines = [('1100', money(sale.total), 0)] if sale.total else []
    lines += [(account, 0, money(amount)) for account, amount in revenue.items() if money(amount)]
    if sale.tax_total:
        lines.append(('2200', 0, money(sale.tax_total)))
    lines += sale_cost_lines(sale)
    return post_journal(key=f'sale:{sale.pk}', description=f'Sale {sale.number}', lines=lines,
        branch=sale.branch_id, date=timezone.localtime(sale.created_at).date(), user=sale.created_by)


def post_collection(payment):
    if payment.status != 'COMPLETED' or not payment.sale_id or not payment.amount:
        return None
    return post_journal(key=f'payment:{payment.pk}', description=f'Payment {payment.sale.number}',
        branch=payment.sale.branch_id, date=timezone.localtime(payment.updated_at).date(),
        user=payment.sale.created_by, lines=paired(cash_code(payment.method), '1100', payment.amount))


def post_purchase(purchase, landed_paid=()):
    """Stock received: inventory at recorded cost; owed to the supplier unless paid in the same step.

    ``landed_paid`` lists (payment_method, amount) for delivery costs paid at once to someone else.
    """
    receipt = purchase.receipt
    inventory = money(sum((line.received_quantity * line.unit_cost + line.landed_cost for line in receipt.lines.all() if not line.uncosted), Decimal(0)))
    if not inventory:
        return None
    lines = [('1200', inventory, 0)]
    paid_now = Decimal(0)
    for method, amount in landed_paid:
        lines.append((cash_code(method), 0, money(amount)))
        paid_now += money(amount)
    lines.append(('2000', 0, inventory - paid_now))
    return post_journal(key=f'purchase:{purchase.pk}', description=f'Stock receipt {receipt.receipt_number}',
        branch=receipt.branch_id, date=timezone.localtime(receipt.received_at).date(), user=purchase.created_by, lines=lines)


def post_cash_entry(entry):
    if not entry.amount:
        return None
    if entry.reversal_of_id:
        original = JournalEntry.objects.filter(source_key=f'cash:{entry.reversal_of_id}').first()
        if original:
            return reverse_journal(original, user=entry.created_by, reason=entry.reason,
                date=timezone.localtime(entry.occurred_at).date(), key=f'cash:{entry.pk}')
        return None  # Historical entry: no invented retrospective ledger.
    account = cash_code(entry.account.payment_method)
    if entry.kind == 'EXPENSE':
        lines = paired('6000', account, -entry.amount)
    elif entry.kind == 'PURCHASE':
        lines = paired('2000', account, -entry.amount)
    elif entry.kind == 'OPENING':
        lines = paired(account, '3000', entry.amount)
    elif entry.kind == 'TRANSFER':
        # Moved to the M-Pesa agency: the agency's own journal adds its float or cash against equity, this takes it
        # out of the part's place the same way, so overall the money only moved (place -> agency float or cash).
        lines = paired('3000', account, -entry.amount)
    else:
        return None  # Sales and agency have their own source posting policies.
    return post_journal(key=f'cash:{entry.pk}', description=entry.reference, lines=lines, branch=entry.branch_id,
        date=timezone.localtime(entry.occurred_at).date(), user=entry.created_by)


@transaction.atomic
def reverse_journal(entry, *, user, reason, date=None, key=None):
    if not reason.strip():
        raise ValidationError('Explain the correction.')
    Organization.objects.select_for_update().get(pk=organization_id())
    entry = JournalEntry.objects.get(pk=entry.pk)
    if entry.reversal_of_id:
        raise ValidationError('A reversal cannot itself be reversed.')
    existing = JournalEntry.objects.filter(reversal_of=entry).first()
    if existing:
        if key and existing.source_key == key:
            return existing
        raise ValidationError('This journal has already been reversed.')
    return post_journal(key=key or f'reversal:{entry.pk}', description=reason, branch=entry.branch_id,
        date=date, user=user, reversal_of=entry,
        lines=[(line.account.code, line.credit, line.debit) for line in entry.lines.select_related('account')])
