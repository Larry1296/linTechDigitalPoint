from apps.tenancy.permissions import has_business_permission, is_business_manager
from collections import defaultdict
from decimal import Decimal
from django.db.models import F, Sum, Q
from django.utils import timezone
from rest_framework import serializers
from apps.catalog.models import ProductVariant
from apps.inventory.models import StockBalance
from apps.mpesa.models import MpesaSession, MpesaReconciliation
from apps.cyber.models import CyberJob
from .models import BusinessUnit, CashEntry, CashAccount, DailyClosing, SupplierPurchase


class Filters(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    employee = serializers.IntegerField(required=False, min_value=1)
    payment_method = serializers.CharField(required=False)
    business_unit = serializers.ChoiceField(choices=BusinessUnit.choices, required=False)
    def validate(self, data):
        if data.get('start') and data.get('end') and data['start'] > data['end']:
            raise serializers.ValidationError('Start must precede end.')
        return data


def filtered_entries(params):
    validator = Filters(data=params)
    validator.is_valid(raise_exception=True)
    data = validator.validated_data
    rows = CashEntry.objects.select_related('account', 'created_by')
    for key, field in [('start', 'occurred_at__date__gte'), ('end', 'occurred_at__date__lte'),
                       ('employee', 'created_by_id'), ('business_unit', 'business_unit'), ('payment_method', 'account__payment_method')]:
        if key in data:
            rows = rows.filter(**{field: data[key]})
    return rows, data


def stock_rows(user):
    sensitive = has_business_permission(user, 'accounting.view_profit')
    rows = []
    for variant in ProductVariant.objects.filter(active=True, product__product_type='STOCK_ITEM').select_related('product__category').prefetch_related('lots__balances__shelf'):
        balances = [balance for lot in variant.lots.all() for balance in lot.balances.all()]
        quantity = sum((b.quantity for b in balances), Decimal('0'))
        available = sum((b.quantity - b.reserved for b in balances), Decimal('0'))
        row = {'id': variant.pk, 'product': str(variant), 'sku': variant.sku, 'quantity': quantity,
               'available': available, 'minimum': variant.minimum_stock, 'low_stock': available <= variant.minimum_stock,
               'shelves': ', '.join(sorted({b.shelf.code for b in balances if b.quantity}))}
        if sensitive:
            row['valuation'] = sum((lot.unit_cost * sum((b.quantity for b in lot.balances.all()), Decimal('0')) for lot in variant.lots.all()), Decimal('0'))
        rows.append(row)
    return rows


def summary(user, params):
    """Accrual revenue, cost of sales and expenses per business unit (from journals), with money
    received shown separately. Money received is cash, never revenue or profit."""
    from datetime import date
    from apps.inventory.dashboard import pnl_rows
    entries, filters = filtered_entries(params)
    profit = has_business_permission(user, 'accounting.view_profit')
    if profit:
        from .investments import book_earnings
        book_earnings()
    start, end = filters.get('start') or date(1900, 1, 1), filters.get('end') or timezone.localdate()
    units = {unit: {'business_unit': unit, 'revenue': Decimal('0'), 'expenses': Decimal('0'), 'stock_corrections': Decimal('0'), 'cogs': Decimal('0'), 'money_received': Decimal('0')}
             for unit in BusinessUnit.values}
    daily = defaultdict(lambda: Decimal('0'))
    monthly = defaultdict(lambda: Decimal('0'))
    interest = Decimal('0')  # investment interest less fees: in the whole business's profit, never a part's
    for row in pnl_rows(start, end):
        if row['field'] == 'interest' and not filters.get('business_unit'):
            interest += row['amount']
        if row['unit'] in units and row['field'] in units[row['unit']] and (not filters.get('business_unit') or row['unit'] == filters['business_unit']):
            units[row['unit']][row['field']] += row['amount']
            if row['field'] == 'revenue':
                daily[str(row['date'])] += row['amount']
                monthly[row['date'].strftime('%Y-%m')] += row['amount']
    for entry in entries.filter(kind='INCOME'):
        units[entry.business_unit]['money_received'] += entry.amount
    totals = {key: sum((u[key] for u in units.values()), Decimal('0')) for key in ['revenue', 'expenses', 'stock_corrections', 'cogs', 'money_received']}
    if profit:
        totals['interest'] = interest
    for row in [*units.values(), totals]:
        if profit:
            row['gross_profit'] = row['revenue'] - row['cogs']
            row['net_profit'] = row['gross_profit'] - row['expenses'] - row['stock_corrections'] + row.get('interest', Decimal('0'))
        else:
            row.pop('cogs')
            row.pop('stock_corrections')
    return {'basis': 'accrual', 'units': list(units.values()), 'totals': totals, 'daily_sales': dict(sorted(daily.items())),
            'monthly_sales': dict(sorted(monthly.items())), 'filters': filters}


def home(user):
    today = timezone.localdate()
    data = summary(user, {'start': today, 'end': today})
    data.update(date=today, low_stock=[r for r in stock_rows(user) if r['low_stock']][:20],
        pending_cyber=CyberJob.objects.exclude(status__in=['COMPLETED', 'CANCELLED']).count(),
        unreconciled_sessions=MpesaSession.objects.filter(status='OPEN').count(),
        cash=list(CashAccount.objects.annotate(balance=Sum('cashentry__amount', filter=Q(cashentry__in=CashEntry.objects.all()))).values('id', 'name', 'balance')),
        recent=list(CashEntry.objects.values('id', 'reference', 'business_unit', 'kind', 'amount', 'occurred_at')[:15]))
    return data
