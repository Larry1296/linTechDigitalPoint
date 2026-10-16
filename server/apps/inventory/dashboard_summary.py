"""The first thing the owner sees: every part of the business together, in plain figures.

Sales of products and services, M-Pesa commission, what the sold items really cost, running costs and the profit or
loss they leave, today and since the business started; and the money the owner should be holding now (drawer, till,
bank), worked out step by step from the cash book, with what each part of the business brought into it. The M-Pesa
agency's cash and float are the agency's money in operation: shown beside the owner's money, never added to it; only
the commission it earns is the owner's. Parts the viewer may not see are None, never guessed."""
from datetime import date
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

ZERO = Decimal('0')
UNITS = ('SHOP', 'CYBER', 'MPESA')  # the agency counts by its commission and costs, never its cash or float


def _figures(rows, units, profit_visible):
    from .dashboard import accrual_totals
    total = accrual_totals(rows, units)
    result = {'products': accrual_totals(rows, ['SHOP'])['revenue'] if 'SHOP' in units else None,
              'services': accrual_totals(rows, ['CYBER'])['revenue'] if 'CYBER' in units else None,
              'commission': accrual_totals(rows, ['MPESA'])['revenue'] if 'MPESA' in units else None,
              'sales': total['revenue']}
    if profit_visible:
        result.update(cost=total['cogs'], expenses=total['expenses'], stock_corrections=total['stock_corrections'], profit=total['profit'])
    else:
        result.update(dict.fromkeys(['cost', 'expenses', 'stock_corrections', 'profit']))
    return result


def _money():
    from apps.accounting.money_check import PARTS, places
    from apps.accounting.money_mode import money_mode, money_names
    found = places()
    parts = {key: sum((next(p['amount'] for p in place['parts'] if p['key'] == key) for place in found), ZERO) for _, key, _ in PARTS}
    brought = {}
    for place in found:
        for row in place['by_part']:
            brought[row['unit']] = brought.get(row['unit'], ZERO) + row['amount']
    return {'expected': sum((place['expected'] for place in found), ZERO), 'mode': money_mode(),
            'places': [{'key': place['key'], 'method': place['method'], 'unit': place['unit'], 'label': place['label'],
                        'expected': place['expected']} for place in found],
            'parts': [{'key': key, 'label': label, 'amount': parts[key]} for _, key, label in PARTS],
            'by_part': [{'unit': unit, 'label': money_names().get(unit, unit), 'amount': amount} for unit, amount in brought.items()]}


def agency_money(with_commission=False):
    """The M-Pesa agency's money in operation (cash in its drawer and float on its line), as last recorded on each
    outlet: the open shift as it stands, or else what the last shift closed with. The business's stock for the agency
    (like goods on the shelves): never profit; the commission it earns is. ``live`` is whether a shift is open; ``as_of`` is when the last closed shift closed when none is.
    ``with_commission`` adds the commission balance the app works out for each outlet. None when the business has no agency."""
    from apps.mpesa.commission_learning import balance_now
    from apps.mpesa.models import MpesaOutlet, MpesaSession
    from apps.mpesa.services import session_balances
    cash = electronic_float = ZERO
    outlets = list(MpesaOutlet.objects.filter(active=True))
    if not outlets:
        return None
    live, as_of, commission = False, None, None
    for outlet in outlets:
        session = outlet.sessions.order_by('-opened_at', '-pk').first()
        if with_commission:
            value = balance_now(outlet.pk)['value']
            if value is not None:
                commission = (commission or ZERO) + value
        if not session:
            continue
        if session.status == MpesaSession.OPEN:
            in_drawer, on_line = session_balances(session)
            live = True
        else:
            in_drawer, on_line = session.closing_cash_actual or ZERO, session.closing_float_actual or ZERO
            if session.closed_at and (as_of is None or session.closed_at > as_of):
                as_of = session.closed_at
        cash, electronic_float = cash + in_drawer, electronic_float + on_line
    result = {'cash': cash, 'float': electronic_float, 'total': cash + electronic_float, 'live': live,
              'as_of': None if live or as_of is None else timezone.localtime(as_of)}
    if with_commission:
        result['commission_balance'] = commission
    return result


def _customers_owe():
    """Sold but not yet paid for: the balance customers still owe the shop."""
    from apps.accounting.models import JournalLine
    return JournalLine.objects.filter(account__code='1100').aggregate(v=Sum(F('debit') - F('credit')))['v'] or ZERO


def owner_summary(*, visible_units, profit_visible, permits):
    from .dashboard import pnl_rows
    units = [unit for unit in UNITS if unit in visible_units]
    if not units:
        return None
    today = timezone.localdate()
    # Everything ever recorded, records dated ahead included (commission is counted on its month's last day), so the
    # running total always shows where sales and profit have reached.
    rows = pnl_rows(date(1900, 1, 1), date(9999, 12, 31))
    rows = [row for row in rows if row['unit'] in units]
    money_allowed = permits('accounting.view_moneycheck')
    from apps.commerce.models import Sale, SaleItem
    channels = ([Sale.POS, Sale.ONLINE] if 'SHOP' in units else []) + ([Sale.CYBER] if 'CYBER' in units else [])
    sold = Sale.objects.filter(status='COMPLETED', channel__in=channels)
    return {'since': min((row['date'] for row in rows), default=None),
            'today': _figures([row for row in rows if row['date'] == today], units, profit_visible),
            'all_time': {**_figures(rows, units, profit_visible), 'count': sold.count(),
                         'items_sold': SaleItem.objects.filter(sale__in=sold).aggregate(v=Sum('quantity'))['v'] or ZERO},
            'money': _money() if money_allowed else None,
            'agency': agency_money() if money_allowed and 'MPESA' in units else None,
            'customers_owe': _customers_owe() if money_allowed else None}
