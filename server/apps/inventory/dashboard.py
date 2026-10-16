"""Tenant-scoped dashboard snapshots from posted books and operational records."""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value, Q
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.accounting.models import CashEntry
from apps.catalog.models import ProductVariant
from apps.commerce.models import Order, Sale, SaleItem
from apps.cyber.models import CyberJob
from apps.mpesa.models import MpesaSession, MpesaTransaction
from apps.tenancy.middleware import effective_modules
from apps.tenancy.permissions import has_business_permission
from .models import StockBalance, StockLot, StockReceipt, Movement
from rest_framework.exceptions import ValidationError

ZERO = Decimal('0')
UNITS = [('SHOP', 'Products / sales', 'pos', 'commerce.view_sale'),
         ('CYBER', 'Services', 'services', 'cyber.view_cyberjob'),
         ('MPESA', 'M-Pesa agency', 'mpesa', 'mpesa.view_mpesasession')]


# Accrual figures come from posted journals. Each P&L account belongs to a business unit; an expense
# belongs to the unit it was recorded for, or is shared between the parts it names; stock losses belong to the shop.
REVENUE_UNIT = {'4000': 'SHOP', '4900': 'SHOP', '4020': 'CYBER', '4010': 'MPESA'}
COST_UNIT = {'5000': 'SHOP', '5010': 'CYBER'}
# Interest earned on investments (e.g. a CIC money market fund) is not a sale of anything: it is kept apart from
# sales and from the trading profit, and investment figures stay on the protected Investments page.
INVESTMENT_INCOME = {'4910'}


def pnl_rows(start, end):
    """[{date, unit, field, amount}] for revenue, cogs and expenses posted between start and end."""
    from apps.accounting.models import Expense, JournalLine
    lines = list(JournalLine.objects.filter(entry__posting_date__range=(start, end), account__kind__in=['REVENUE', 'COGS', 'EXPENSE'])
                 .values('account__code', 'account__name', 'account__kind', 'entry__source_key', 'entry__posting_date')
                 .annotate(d=Sum('debit'), c=Sum('credit')))
    expense_ids, cash_ids = set(), set()
    for line in lines:
        prefix, _, ident = line['entry__source_key'].partition(':')
        if line['account__kind'] == 'EXPENSE' and ident.isdigit():
            if prefix in ('expense', 'expense-cancel'):
                expense_ids.add(int(ident))
            elif prefix == 'cash':
                cash_ids.add(int(ident))
    expense_units = {pk: (unit, shares) for pk, unit, shares in Expense.objects.filter(pk__in=expense_ids).values_list('pk', 'business_unit', 'unit_shares')}
    cash_units = dict(CashEntry.objects.filter(pk__in=cash_ids).values_list('pk', 'business_unit'))
    rows = []
    for line in lines:
        code, kind = line['account__code'], line['account__kind']
        prefix, _, ident = line['entry__source_key'].partition(':')
        if kind == 'REVENUE' and code in INVESTMENT_INCOME:
            unit, field, amount = 'SHOP', 'interest', line['c'] - line['d']
        elif kind == 'REVENUE':
            unit, field, amount = REVENUE_UNIT.get(code, 'SHOP'), 'revenue', line['c'] - line['d']
        elif kind == 'COGS':
            unit, field, amount = COST_UNIT.get(code, 'SHOP'), 'cogs', line['d'] - line['c']
        else:
            number = int(ident) if ident.isdigit() else None
            if prefix in ('expense', 'expense-cancel'):
                unit, shares = expense_units.get(number, (None, None))
                if shares:
                    # A cost shared between the parts: each part carries its share (a cancellation takes it back the same way).
                    for part, amount in shared(line['d'] - line['c'], shares).items():
                        rows.append({'date': line['entry__posting_date'], 'unit': part, 'field': 'expenses', 'amount': amount,
                                     'account': line['account__name'], 'code': code})
                    continue
            elif prefix == 'cash':
                unit = cash_units.get(number)
            else:
                unit = None
            # Stock count gains and losses (6100) are kept apart from running costs, so "Expenses" means
            # bills actually incurred; profit still takes both into account.
            field = 'stock_corrections' if code == '6100' else 'expenses'
            unit, field, amount = unit or 'SHOP', field, line['d'] - line['c']
        rows.append({'date': line['entry__posting_date'], 'unit': unit, 'field': field, 'amount': amount,
                     'account': line['account__name'], 'code': code})
    return rows


def shared(amount, shares):
    """{part: amount} for one journal line of a shared expense, in proportion to the expense's shares."""
    from apps.accounting.expense_shares import divide
    parts = divide(abs(amount), {part: Decimal(str(value)) for part, value in shares.items()})
    return {part: value if amount >= 0 else -value for part, value in parts.items()}


def accrual_totals(rows, units):
    result = dict(revenue=ZERO, cogs=ZERO, expenses=ZERO, stock_corrections=ZERO)
    for row in rows:
        if row['unit'] in units and row['field'] in result:
            result[row['field']] += row['amount']
    result['profit'] = result['revenue'] - result['cogs'] - result['expenses'] - result['stock_corrections']
    return result


def unit_series(trend_rows, period_rows, units, profit_visible, first_month, start, end):
    """Each part of the business side by side over time, for the dashboard's comparison charts: month by month for the
    last twelve months, and day by day over the chosen dates (when they span at most two months). Each point carries
    ``<PART>_sales``, ``<PART>_costs`` (running costs, shared ones by each part's share) and ``<PART>_profit``, and the
    same for ``TOTAL``, the whole business, which the parts add up to (costs and profit None when the viewer may not
    see them)."""
    keys = [key for key, _, _, _ in UNITS if key in units]
    if len(keys) < 2:
        return [], []

    def point(rows, **label):
        values = {}
        for key, part in [*((key, [key]) for key in keys), ('TOTAL', keys)]:
            totals = accrual_totals(rows, part)
            values[f'{key}_sales'] = totals['revenue']
            values[f'{key}_costs'] = totals['expenses'] if profit_visible else None
            values[f'{key}_profit'] = totals['profit'] if profit_visible else None
        return {**label, **values}

    months = {}
    for row in trend_rows:
        months.setdefault(row['date'].strftime('%Y-%m'), []).append(row)
    trend = [point(months.get(shift_month(first_month, offset).strftime('%Y-%m'), []), month=shift_month(first_month, offset).strftime('%Y-%m'))
             for offset in range(12)]
    days = []
    if (end - start).days <= 62:
        by_day = {}
        for row in period_rows:
            by_day.setdefault(row['date'], []).append(row)
        days = [point(by_day.get(start + timedelta(days=n), []), date=(start + timedelta(days=n)).isoformat()) for n in range((end - start).days + 1)]
    return trend, days


def money_received(start, end):
    """Customer money actually received (less refunds): cash, not revenue."""
    from apps.accounting.ledger import CASH_CODES
    from apps.accounting.models import JournalEntry, JournalLine
    codes = set(CASH_CODES.values()) - {'1300', '1310'}
    return (JournalLine.objects.filter(account__code__in=codes, entry__posting_date__range=(start, end))
            .filter(entry__in=JournalEntry.objects.filter(lines__account__code='1100'))
            .aggregate(v=Sum(F('debit') - F('credit')))['v'] or ZERO)


def shift_month(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    return day.replace(year=index // 12, month=index % 12 + 1, day=1)


def book_totals(rows):
    result = dict(revenue=ZERO, cogs=ZERO, expenses=ZERO)
    for row in rows:
        if row['kind'] == 'INCOME':
            result['revenue'] += row['amount'] or ZERO
            result['cogs'] += row['cogs'] or ZERO
        elif row['kind'] == 'EXPENSE':
            # Reversals are positive expense entries; never take abs().
            result['expenses'] -= row['amount'] or ZERO
    result['profit'] = result['revenue'] - result['cogs'] - result['expenses']
    return result


def dashboard_snapshot(request):
    now = timezone.now()
    today = timezone.localdate(now)
    try:
        start = date.fromisoformat(request.query_params.get('start', today.replace(day=1).isoformat()))
        end = date.fromisoformat(request.query_params.get('end', today.isoformat()))
    except ValueError:
        raise ValidationError('Use YYYY-MM-DD for the report dates.')
    if start.year < 1900:
        raise ValidationError('Report dates must be from 1900 onwards.')
    if start > end or end > today:
        raise ValidationError('Choose an ordered date range ending no later than today.')
    enabled = effective_modules(request.organization)
    permits = lambda permission: has_business_permission(request.user, permission)
    profit_visible = permits('accounting.view_profit')
    visible_units = [key for key, _, module, permission in UNITS if module in enabled and permits(permission)]
    books = CashEntry.objects.filter(business_unit__in=visible_units, occurred_at__lte=now)
    daily = pnl_rows(today, today)
    totals = accrual_totals(daily, visible_units)
    channels = []
    if 'SHOP' in visible_units:
        channels += [Sale.POS, Sale.ONLINE]
    if 'CYBER' in visible_units:
        channels += [Sale.CYBER]
    sales = Sale.objects.filter(status='COMPLETED', channel__in=channels, created_at__date=today, created_at__lte=now)
    data = {
        'organization': {'id': request.organization.pk, 'name': request.organization.name,
                         'business_type': request.organization.business_type, 'currency': request.organization.currency,
                         'timezone': request.organization.timezone},
        'enabled_modules': sorted(enabled), 'generated_at': now, 'business_date': today,
        'financial_scope': 'enabled_operations' if len(visible_units) == sum(module in enabled for _, _, module, _ in UNITS) else 'permitted_operations',
        'today': {**totals, 'sales': sales.count(), 'items_sold': SaleItem.objects.filter(sale__in=sales).aggregate(v=Sum('quantity'))['v'] or ZERO,
                  'restricted': not bool(visible_units)},
        'business_units': [], 'financial_trend': [],
    }
    for key, name, module, permission in UNITS:
        allowed = key in visible_units
        unit = accrual_totals(daily, [key])
        if not allowed:
            unit = {field: None for field in unit}
        elif not profit_visible:
            unit.update(cogs=None, expenses=None, stock_corrections=None, profit=None)
        data['business_units'].append({'key': key, 'name': name, 'enabled': module in enabled, 'restricted': not allowed, **unit})
        if key == 'SHOP':
            data['retail'] = {**unit, 'sales': sales.exclude(channel=Sale.CYBER).count() if allowed else None, 'restricted': not allowed}
        elif key == 'CYBER':
            jobs = CyberJob.objects.filter(created_at__lte=now).exclude(sale__status='CANCELLED')
            data['cyber'] = {**unit, 'active_jobs': jobs.exclude(status__in=['COMPLETED', 'CANCELLED']).count() if allowed else None,
                             'ready_jobs': jobs.filter(status='READY').count() if allowed else None,
                             'jobs_today': jobs.filter(created_at__date=today).count() if allowed else None, 'restricted': not allowed}
        else:
            from .dashboard_summary import agency_money
            shifts = MpesaSession.objects.filter(status='OPEN').count() if allowed else 0
            # The open shifts as they stand; between shifts, what the last shift closed with, so it never reads 0.
            agency = (agency_money(with_commission=True) if allowed else None) or {}
            transactions = MpesaTransaction.objects.filter(occurred_at__date=today, occurred_at__lte=now, status='POSTED', reversal_of__isnull=True, reversal__isnull=True)
            data['mpesa'] = {'restricted': not allowed, 'commission': unit['revenue'], 'principal_revenue': 0,
                             'cash': agency.get('cash', ZERO) if allowed else None,
                             'float': agency.get('float', ZERO) if allowed else None,
                             'in_operation': agency.get('total', ZERO) if allowed else None,
                             'live': agency.get('live', False), 'as_of': agency.get('as_of'),
                             'commission_balance': agency.get('commission_balance'),
                             'open_sessions': shifts if allowed else None,
                             'transaction_count': transactions.count() if allowed else None,
                             'deposits': (transactions.filter(transaction_type='CUSTOMER_DEPOSIT').aggregate(v=Sum('amount'))['v'] or ZERO) if allowed else None,
                             'withdrawals': (transactions.filter(transaction_type='CUSTOMER_WITHDRAWAL').aggregate(v=Sum('amount'))['v'] or ZERO) if allowed else None,
                             'airtime': (transactions.filter(transaction_type='AIRTIME_SALE').aggregate(v=Sum('amount'))['v'] or ZERO) if allowed else None}
    if not visible_units:
        data['today'] = {key: None for key in data['today']}
        data['today']['restricted'] = True
    elif not profit_visible:
        data['today'].update(cogs=None, profit=None, expenses=None, stock_corrections=None)

    inventory_allowed = 'inventory' in enabled and permits('catalog.view_product')
    data['inventory'] = {'restricted': not inventory_allowed, **dict.fromkeys(['physical', 'available', 'cost', 'retail', 'potential_margin', 'low_stock', 'total_skus'])}
    if inventory_allowed:
        variants = ProductVariant.objects.filter(active=True, product__active=True, product__product_type='STOCK_ITEM')
        quantities = variants.annotate(available=Coalesce(Sum(F('lots__balances__quantity') - F('lots__balances__reserved'), filter=Q(lots__balances__in=StockBalance.objects.all())), ZERO, output_field=DecimalField()))
        balances = StockBalance.objects.filter(lot__variant__in=variants)
        values = balances.aggregate(physical=Sum('quantity'), available=Sum(F('quantity') - F('reserved')),
                                    cost=Sum(ExpressionWrapper(F('quantity') * F('lot__unit_cost'), output_field=DecimalField())),
                                    retail=Sum(ExpressionWrapper(F('quantity') * F('lot__variant__selling_price'), output_field=DecimalField())))
        values = {key: value or ZERO for key, value in values.items()}
        values['potential_margin'] = values['retail'] - values['cost']
        if not profit_visible:
            values.update(cost=None, potential_margin=None)
        data['inventory'].update(values, total_skus=variants.count(), low_stock=quantities.filter(available__lte=F('minimum_stock')).count())
    orders_allowed = 'pos' in enabled and permits('commerce.view_order')
    data['orders'] = {'restricted': not orders_allowed,
                      'awaiting_payment': Order.objects.filter(payment_status='PENDING').exclude(status='CANCELLED').count() if orders_allowed else None,
                      'awaiting_fulfillment': Order.objects.filter(payment_status='PAID').exclude(fulfillment_status='COMPLETED').exclude(status='CANCELLED').count() if orders_allowed else None}

    # Lots cover receipts, legacy receiving and opening stock without counting
    # split shelf placements twice. Corrections update the lot's quantity/cost.
    stock_allowed = inventory_allowed and profit_visible
    stock_lots = StockLot.objects.filter(received_at__lte=now)
    # A receipt marked as opening balance is stock the business already owned: opening stock, never a purchase.
    opening_receipt = Q(receipt_line__receipt__document_status=StockReceipt.OPENING_BALANCE)
    purchase_lots = stock_lots.filter(pk__in=Movement.objects.filter(movement_type='PURCHASE_RECEIPT').values('lot_id')).exclude(opening_receipt)
    opening_lots = stock_lots.filter(Q(pk__in=Movement.objects.filter(movement_type='OPENING_STOCK').values('lot_id')) | opening_receipt)
    stock_value = ExpressionWrapper(F('received_quantity') * F('unit_cost'), output_field=DecimalField())
    def stock_total(lots):
        return lots.filter(received_at__date__range=(start, end)).aggregate(value=Sum(stock_value))['value'] or ZERO

    period_rows = pnl_rows(start, end)
    period = accrual_totals(period_rows, visible_units)
    period['gross_profit'] = period['revenue'] - period['cogs']
    if not visible_units:
        period = dict.fromkeys(period)
    elif not profit_visible:
        period.update(cogs=None, expenses=None, stock_corrections=None, gross_profit=None, profit=None)
    period.update(start=start, end=end,
                  purchases=stock_total(purchase_lots) if stock_allowed else None,
                  opening_stock=stock_total(opening_lots) if stock_allowed else None)
    period['money_received'] = money_received(start, end) if visible_units else None
    period['basis'] = "accrual"
    data['period_summary'] = period
    # Commission the M-Pesa agency earned in these dates that Safaricom has not paid yet: it is not in the books until it
    # is recorded, so profit is shown with and without it.
    data['mpesa_unpaid'] = None
    if 'MPESA' in visible_units and profit_visible:
        from apps.mpesa.commission_learning import unpaid
        coming = unpaid(start, end)
        if coming['amount']:
            data['mpesa_unpaid'] = {**coming, 'profit_with': period['profit'] + coming['amount']}
    # Each part of the business over the same dates, for the dashboard's "where the sales came from".
    from apps.accounting.money_mode import has_parts, part_names
    names = part_names()
    data['has_parts'] = has_parts()
    data['unit_period'] = [{'key': key, 'name': names.get(key, name), **{field: value if profit_visible or field == 'revenue' else None
                            for field, value in accrual_totals(period_rows, [key]).items()}}
                           for key, name, _, _ in UNITS if key in visible_units]
    data['expense_breakdown'] = []
    if profit_visible and visible_units:
        grouped_expenses = {}
        for row in period_rows:
            if row['field'] == 'expenses' and row['unit'] in visible_units:
                name = 'Other recorded expenses' if row['code'] == '6000' else row['account']
                grouped_expenses[(name, row['unit'])] = grouped_expenses.get((name, row['unit']), ZERO) + row['amount']
        data['expense_breakdown'] = [dict(category=name, business_unit=unit, amount=amount)
                                     for (name, unit), amount in sorted(grouped_expenses.items()) if amount]

    if visible_units:
        month_start = shift_month(today.replace(day=1), -11)
        trend_rows = pnl_rows(month_start, today)
        purchases = {row['month'].strftime('%Y-%m'): row['amount'] for row in purchase_lots.filter(received_at__date__gte=month_start).annotate(month=TruncMonth('received_at')).values('month').annotate(amount=Sum(stock_value))} if stock_allowed else {}
        for offset in range(12):
            month = shift_month(month_start, offset).strftime('%Y-%m')
            values = accrual_totals([row for row in trend_rows if row['date'].strftime('%Y-%m') == month], visible_units)
            verdict = 'PROFIT' if values['profit'] > 0 else 'LOSS' if values['profit'] < 0 else 'BREAK_EVEN'
            data['financial_trend'].append({'month': month, 'sales': values['revenue'],
                'purchases': purchases.get(month, ZERO) if stock_allowed else None,
                'expenses': values['expenses'] if profit_visible else None, 'cogs': values['cogs'] if profit_visible else None,
                'stock_corrections': values['stock_corrections'] if profit_visible else None,
                'profit': values['profit'] if profit_visible else None, 'verdict': verdict if profit_visible else 'RESTRICTED'})
    data['unit_trend'], data['unit_days'] = unit_series(trend_rows if visible_units else [], period_rows, visible_units, profit_visible,
                                                        month_start if visible_units else today, start, end)
    from .dashboard_analytics import enrich_dashboard
    enrich_dashboard(data, books=books, purchase_lots=purchase_lots, stock_value=stock_value,
                     start=start, end=end, now=now, channels=channels, visible_units=visible_units,
                     profit_visible=profit_visible, stock_allowed=stock_allowed, permits=permits)
    from .dashboard_records import records_summary
    data['records'] = records_summary(enabled=enabled, visible_units=visible_units, channels=channels,
                                      profit_visible=profit_visible, permits=permits)
    from .dashboard_summary import owner_summary
    data['owner_summary'] = owner_summary(visible_units=visible_units, profit_visible=profit_visible, permits=permits)
    return data
