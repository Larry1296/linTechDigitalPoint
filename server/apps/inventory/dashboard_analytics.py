"""Additional tenant-scoped accounting panels for the business dashboard."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Prefetch, Sum
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.utils import timezone

from apps.accounting.models import CashEntry, SupplierPurchase
from apps.commerce.models import Sale, SaleItem
from apps.commerce.returns import item_sales, sale_amounts, sale_balance

ZERO = Decimal('0')


def enrich_dashboard(data, *, books, purchase_lots, stock_value, start, end, now,
                     channels, visible_units, profit_visible, stock_allowed, permits):
    from .dashboard import accrual_totals, pnl_rows
    days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    if start.day == 1 and start.month == end.month and start.year == end.year:
        previous_start = previous_end.replace(day=1)
        previous_end = previous_end.replace(day=min(end.day, previous_end.day))
    else:
        previous_start = start - timedelta(days=days)
    previous = accrual_totals(pnl_rows(previous_start, previous_end), visible_units)
    previous['purchases'] = purchase_lots.filter(received_at__date__range=(previous_start, previous_end)).aggregate(
        value=Sum(stock_value))['value'] or ZERO
    comparisons = {}
    for field in ['revenue', 'expenses', 'purchases', 'profit']:
        current = data['period_summary'][field]
        old = previous[field]
        allowed = stock_allowed if field == 'purchases' else bool(visible_units) and (field == 'revenue' or profit_visible)
        comparisons[field] = {'previous': old if allowed else None,
                              'change': current - old if allowed else None,
                              'percent': (current - old) / abs(old) * 100 if allowed and old else None}
    data['comparison'] = {'start': previous_start, 'end': previous_end, 'metrics': comparisons}
    period = data['period_summary']
    period['profit_margin'] = period['profit'] / period['revenue'] * 100 if period['profit'] is not None and period['revenue'] else None

    granularity = 'day' if days <= 366 else 'month'
    truncate = TruncDate if granularity == 'day' else TruncMonth
    grouped = defaultdict(list)
    for row in pnl_rows(start, end):
        key = row['date'].isoformat() if granularity == 'day' else row['date'].strftime('%Y-%m')
        grouped[key].append(row)
    series = []
    cursor = start if granularity == 'day' else start.replace(day=1)
    while cursor <= end:
        key = cursor.isoformat() if granularity == 'day' else cursor.strftime('%Y-%m')
        totals = accrual_totals(grouped[key], visible_units)
        if not visible_units:
            totals = dict.fromkeys(totals)
        elif not profit_visible:
            totals.update(expenses=None, stock_corrections=None, cogs=None, profit=None)
        series.append({'date': key, **totals})
        cursor = cursor + timedelta(days=1) if granularity == 'day' else (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    data['performance'] = {'granularity': granularity, 'points': series}

    # Customer obligations are completed sales, not unpaid shopping-cart orders.
    # Payment reversals are netted against their original ledger source.
    as_of = books.filter(occurred_at__date__lte=end)
    source_totals = dict(as_of.filter(kind='INCOME').annotate(
        source=Coalesce('reversal_of__source_key', 'source_key')).values('source').annotate(value=Sum('amount')).values_list('source', 'value'))
    sales = Sale.objects.filter(status='COMPLETED', channel__in=channels, created_at__date__lte=end,
                                created_at__lte=now).select_related('customer').prefetch_related('payments', Prefetch('items', queryset=SaleItem.objects.filter(sale__created_at__date__gte=start).select_related('variant__product')))
    debtors = []
    outstanding = ZERO
    period_billed = ZERO
    period_collected = ZERO
    top_items = {}
    for sale in sales:
        # After returns and credit/debit notes: what the customer was charged and what they actually paid.
        charged, collected = sale_amounts(sale)
        balance = max(sale_balance(sale), ZERO)
        if balance:
            outstanding += balance
            debtors.append({'reference': sale.number, 'customer': sale.customer.get_full_name() or sale.customer.username if sale.customer else 'Walk-in customer', 'amount': balance})
        # created_at uses the business timezone, matching the query date filters.
        if timezone.localtime(sale.created_at).date() < start:
            continue
        period_billed += charged
        period_collected += min(max(collected, ZERO), charged)
        kept = item_sales(sale)
        for item in sale.items.all():
            quantity, amount = kept.get(item.pk, (item.quantity, item.net_amount))
            if quantity <= 0 and not amount:
                continue
            row = top_items.setdefault(item.variant_id, {'id': item.variant_id, 'name': f'{item.variant.product.name} — {item.variant.name}',
                                                        'sku': item.variant.sku, 'quantity': ZERO, 'sales': ZERO})
            row['quantity'] += quantity
            row['sales'] += amount
    receivables_allowed = bool(channels) and permits('commerce.view_sale') and permits('commerce.view_payment')
    data['receivables'] = {'restricted': not receivables_allowed, 'as_of': end,
                           'outstanding': outstanding if receivables_allowed else None,
                           'count': len(debtors) if receivables_allowed else None,
                           'rows': sorted(debtors, key=lambda row: row['amount'], reverse=True)[:10] if receivables_allowed else []}
    data['collections'] = {'restricted': not receivables_allowed,
                           'period_billed': period_billed if receivables_allowed else None,
                           'collected_on_period_sales': period_collected if receivables_allowed else None,
                           'period_outstanding': period_billed - period_collected if receivables_allowed else None,
                           'rate': period_collected / period_billed * 100 if receivables_allowed and period_billed else None}
    data['top_items'] = sorted(top_items.values(), key=lambda row: row['quantity'], reverse=True)[:10]

    payables_allowed = stock_allowed and permits('accounting.view_supplierpurchase')
    data['payables'] = {'restricted': not payables_allowed, 'as_of': end, 'outstanding': None, 'count': None, 'rows': []}
    if payables_allowed:
        # Only receipt purchases have recorded supplier settlements. Opening
        # stock and legacy lots cannot establish a supplier liability.
        from apps.accounting.services import purchase_outstanding
        rows = []
        for purchase in SupplierPurchase.objects.filter(receipt__received_at__date__lte=end, receipt__received_at__lte=now).select_related('receipt', 'supplier').prefetch_related('receipt__lines'):
            balance = max(purchase_outstanding(purchase), ZERO)
            if balance:
                rows.append({'reference': purchase.receipt.receipt_number, 'supplier': purchase.supplier.name if purchase.supplier else purchase.receipt.supplier_name or 'Unspecified supplier', 'amount': balance})
        data['payables'].update(outstanding=sum((row['amount'] for row in rows), ZERO), count=len(rows),
                                rows=sorted(rows, key=lambda row: row['amount'], reverse=True)[:10])

    ledger_allowed = profit_visible and permits('accounting.view_cashentry')
    data['account_balances'] = list(as_of.values('account__name', 'account__payment_method', 'business_unit').annotate(
        balance=Sum('amount')).order_by('account__name')) if ledger_allowed else None
    if ledger_allowed:
        # Net worth: what the business owns less what it owes, from where each figure really lives.
        from apps.accounting.net_worth import snapshot
        inventory = data.get('inventory') or {}
        data['net_worth'] = snapshot(stock=None if inventory.get('restricted') else inventory.get('cost'),
                                     receivables=data['receivables']['outstanding'], payables=data['payables']['outstanding'])
    else:
        data['net_worth'] = None
    data['recent_entries'] = list(books.filter(occurred_at__date__range=(start, end)).values(
        'id', 'reference', 'kind', 'business_unit', 'amount', 'occurred_at').order_by('-occurred_at', '-pk')[:15]) if ledger_allowed else None
