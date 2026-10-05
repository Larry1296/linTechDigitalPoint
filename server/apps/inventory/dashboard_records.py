"""Everything the business has recorded so far, in one place for its owner: what it sells, what is on the shelves,
every sale and payment, service jobs, the M-Pesa agency, money spent, lent and invested.

Money figures come from the same places as the rest of the dashboard (sales, cost and profit from the posted books),
so they agree with the dashboard's own totals. Parts the viewer may not see are None, never guessed."""
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

ZERO = Decimal('0')


def _sum(rows, field):
    return rows.aggregate(v=Sum(field))['v'] or ZERO


def _catalogue():
    from apps.catalog.models import Brand, Category, Product, ProductVariant
    items = ProductVariant.objects.filter(product__product_type=Product.STOCK_ITEM)
    services = ProductVariant.objects.filter(product__product_type=Product.SERVICE)
    return {'categories': Category.objects.count(), 'brands': Brand.objects.count(),
            'products': Product.objects.filter(product_type=Product.STOCK_ITEM).count(),
            'items': items.count(), 'items_active': items.filter(active=True, product__active=True).count(),
            'services': services.count()}


def _stock(profit_visible):
    from .models import StockBalance, StockLot
    lots = StockLot.objects.all()
    on_shelves = StockBalance.objects.filter(quantity__gt=0)
    result = {'units_received': _sum(lots, 'received_quantity'), 'units_on_shelves': _sum(StockBalance.objects.all(), 'quantity'),
              'items_in_stock': on_shelves.values('lot__variant').distinct().count(),
              'deliveries': lots.count(), 'without_buying_price': lots.filter(cost_status=StockLot.UNCOSTED, remaining_quantity__gt=0).count(),
              'below_cost': []}
    if profit_visible:
        # Items on the shelves whose selling price is below what they cost: sold as priced, each one is a loss.
        cost = ExpressionWrapper(F('quantity') * F('lot__unit_cost'), output_field=DecimalField())
        rows = (on_shelves.values('lot__variant', 'lot__variant__product__name', 'lot__variant__name', 'lot__variant__selling_price', 'lot__variant__pack_size')
                .annotate(units=Sum('quantity'), value=Sum(cost)))
        for row in rows:
            unit_cost = row['value'] / row['units']
            price = row['lot__variant__selling_price']
            if price < unit_cost:
                name = row['lot__variant__product__name']
                if row['lot__variant__name'] and row['lot__variant__name'] not in ('Standard', name):
                    name = f"{name} — {row['lot__variant__name']}"
                result['below_cost'].append({'id': row['lot__variant'], 'name': name, 'quantity': row['units'],
                                             'unit_cost': unit_cost.quantize(Decimal('0.01')), 'selling_price': price})
        result['below_cost'].sort(key=lambda row: row['name'])
    return result


def _sales(channels, books, profit_visible):
    from apps.commerce.models import Payment, Sale, SaleItem, SaleReturn
    sales = Sale.objects.filter(channel__in=channels)
    done = sales.filter(status='COMPLETED')
    payments = Payment.objects.filter(sale__channel__in=channels)
    by_status = {status: total for status, total in payments.values_list('status').annotate(total=Sum('amount'))}
    by_method = {method: total for method, total in payments.filter(status='COMPLETED').values_list('method').annotate(total=Sum('amount'))}
    returns = SaleReturn.objects.filter(sale__channel__in=channels)
    return {'completed': done.count(), 'cancelled': sales.filter(status='CANCELLED').count(),
            'by_channel': dict(done.values_list('channel').annotate(n=Count('id'))),
            'units_sold': _sum(SaleItem.objects.filter(sale__in=done), 'quantity') - _sum(SaleItem.objects.filter(sale__in=done), 'returned_quantity'),
            'revenue': books['revenue'], 'cogs': books['cogs'] if profit_visible else None,
            'gross_profit': books['revenue'] - books['cogs'] if profit_visible else None,
            'returns': returns.count(), 'refunded': _sum(returns, 'refund_amount'),
            'paid': by_status.get('COMPLETED', ZERO), 'paid_by_method': by_method,
            'refunded_payments': by_status.get('REFUNDED', ZERO), 'reversed_payments': by_status.get('REVERSED', ZERO),
            'failed_payments': by_status.get('FAILED', ZERO), 'waiting_payments': by_status.get('PENDING', ZERO) + by_status.get('MANUAL_REVIEW', ZERO)}


def _services():
    from apps.cyber.models import CyberJob
    # A job whose sale was cancelled (refunded) is cancelled, whatever its own status says, as on the rest of the dashboard.
    cancelled = Q(status='CANCELLED') | Q(sale__status='CANCELLED')
    jobs = CyberJob.objects.exclude(cancelled)
    done, open_jobs = jobs.filter(status='COMPLETED'), jobs.exclude(status='COMPLETED')
    return {'completed': done.count(), 'completed_value': _sum(done, 'total'),
            'in_progress': open_jobs.count(), 'in_progress_value': _sum(open_jobs, 'total'),
            'cancelled': CyberJob.objects.filter(cancelled).count()}


def _mpesa(commission):
    from apps.mpesa.models import MpesaOutlet, MpesaSession, MpesaTransaction
    # A reversed transaction and its reversal cancel out, so neither is counted.
    kept = MpesaTransaction.objects.filter(status='POSTED', reversal_of__isnull=True, reversal__isnull=True)
    deposits, withdrawals = kept.filter(transaction_type='CUSTOMER_DEPOSIT'), kept.filter(transaction_type='CUSTOMER_WITHDRAWAL')
    return {'outlets': MpesaOutlet.objects.count(), 'shifts_open': MpesaSession.objects.filter(status=MpesaSession.OPEN).count(),
            'shifts_closed': MpesaSession.objects.filter(status=MpesaSession.CLOSED).count(),
            'deposits': deposits.count(), 'deposits_value': _sum(deposits, 'amount'),
            'withdrawals': withdrawals.count(), 'withdrawals_value': _sum(withdrawals, 'amount'),
            'float_topups': _sum(kept.filter(transaction_type='FLOAT_TOPUP'), 'amount'),
            'commission': commission}


def _money(expenses):
    from apps.accounting.investments import value
    from apps.accounting.loans import outstanding
    from apps.accounting.models import Expense, Investment, Loan
    loans = Loan.objects.filter(cancelled_at__isnull=True)
    investments = list(Investment.objects.all())
    return {'expenses': Expense.objects.count(), 'expenses_value': expenses,
            'loans': loans.count(), 'loans_value': _sum(loans, 'amount'), 'loans_outstanding': sum((outstanding(loan) for loan in loans), ZERO),
            'investments': len(investments), 'investments_value': sum((value(i) for i in investments), ZERO)}


def records_summary(*, enabled, visible_units, channels, profit_visible, permits):
    from .dashboard import accrual_totals, pnl_rows
    today = timezone.localdate()
    rows = pnl_rows(date(1900, 1, 1), today)
    sales_units = [unit for unit in ('SHOP', 'CYBER') if unit in visible_units]
    books = accrual_totals(rows, sales_units)
    everything = accrual_totals(rows, visible_units)
    inventory_allowed = 'inventory' in enabled and permits('catalog.view_product')
    money_allowed = profit_visible and permits('accounting.view_cashentry')
    return {
        'since': min((row['date'] for row in rows), default=None),
        'catalogue': _catalogue() if inventory_allowed else None,
        'stock': _stock(profit_visible) if inventory_allowed else None,
        'sales': _sales(channels, books, profit_visible) if channels else None,
        'services': _services() if 'CYBER' in visible_units else None,
        'mpesa': _mpesa(accrual_totals(rows, ['MPESA'])['revenue']) if 'MPESA' in visible_units else None,
        'money': _money(everything['expenses']) if money_allowed else None,
        'profit': {key: everything[key] for key in ('revenue', 'cogs', 'expenses', 'stock_corrections', 'profit')} if profit_visible and visible_units else None,
    }
