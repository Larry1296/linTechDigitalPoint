"""The first thing the owner sees: the business without the M-Pesa agency, in plain figures.

Sales of products and services, what the sold items really cost, running costs and the profit or loss they leave,
today and since the business started; and the money the owner should be holding now (drawer, till, bank), worked
out step by step from the cash book. M-Pesa agency cash, float and commission are customers' and Safaricom's money,
checked on the M-Pesa desk, so none of it is here. Parts the viewer may not see are None, never guessed."""
from datetime import date
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

ZERO = Decimal('0')
UNITS = ('SHOP', 'CYBER')  # never the M-Pesa agency


def _figures(rows, units, profit_visible):
    from .dashboard import accrual_totals
    total = accrual_totals(rows, units)
    result = {'products': accrual_totals(rows, ['SHOP'])['revenue'] if 'SHOP' in units else None,
              'services': accrual_totals(rows, ['CYBER'])['revenue'] if 'CYBER' in units else None,
              'sales': total['revenue']}
    if profit_visible:
        result.update(cost=total['cogs'], expenses=total['expenses'], stock_corrections=total['stock_corrections'], profit=total['profit'])
    else:
        result.update(dict.fromkeys(['cost', 'expenses', 'stock_corrections', 'profit']))
    return result


def _money():
    from apps.accounting.money_check import PARTS, places
    found = places()
    parts = {key: sum((next(p['amount'] for p in place['parts'] if p['key'] == key) for place in found), ZERO) for _, key, _ in PARTS}
    return {'expected': sum((place['expected'] for place in found), ZERO),
            'places': [{'method': place['method'], 'label': place['label'], 'expected': place['expected']} for place in found],
            'parts': [{'key': key, 'label': label, 'amount': parts[key]} for _, key, label in PARTS]}


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
    rows = pnl_rows(date(1900, 1, 1), today)
    rows = [row for row in rows if row['unit'] in units]
    money_allowed = permits('accounting.view_moneycheck')
    return {'since': min((row['date'] for row in rows), default=None),
            'today': _figures([row for row in rows if row['date'] == today], units, profit_visible),
            'all_time': _figures(rows, units, profit_visible),
            'money': _money() if money_allowed else None,
            'customers_owe': _customers_owe() if money_allowed else None}
