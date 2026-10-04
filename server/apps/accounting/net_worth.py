"""What the business owns, what it owes and the difference (its net worth), from where each figure really lives.

- Shop money (drawer, Lipa na M-Pesa till, bank): what the cash book says should be there, the same figure Money check
  compares against a count. The last count is shown next to it, so a gap is visible rather than hidden.
- M-Pesa agency: the money in operation now. With a shift open that is its opening cash and float plus everything
  since; with none open, what was counted when the last shift closed. The agency's cash book lines are not used: they
  only hold the day's movements, not the money the shift started with.
- Investments at their recorded value (estimated interest is not counted until a statement confirms it), money lent
  and not yet repaid, commission Safaricom still owes, what customers owe and stock at what it cost.
- Owed: suppliers for stock received and running costs recorded but not yet paid.

Anything the viewer is not allowed to see is left out and listed as such, never guessed. A copy is kept once a day so
the net worth can be followed over time.
"""
from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone

ZERO = Decimal("0")
OUTSIDE_AGENCY = ["CASH", "MPESA", "BANK", "OTHER"]


def _shop_money():
    from .money_check import places
    rows = []
    for place in places():
        last = place["last_check"]
        rows.append({"key": f"shop-{place['method'].lower()}", "label": place["label"], "amount": place["expected"], "method": place["method"],
                     "counted": last["actual"] if last else None, "counted_at": last["created_at"] if last else None,
                     "difference": last["difference"] if last else None})
    # Commission paid to the owner's own M-Pesa, bank or cash is the agency's money kept outside the shift.
    from .models import CashEntry
    kept = CashEntry.objects.filter(business_unit="MPESA", account__payment_method__in=OUTSIDE_AGENCY).aggregate(v=Sum("amount"))["v"] or ZERO
    if kept:
        rows.append({"key": "agency-kept", "label": "Agency commission kept outside the shift", "amount": kept, "method": None,
                     "counted": None, "counted_at": None, "difference": None})
    return rows


def _agency_money():
    from apps.mpesa.models import MpesaOutlet, MpesaSession
    from apps.mpesa.services import session_balances
    rows = []
    for outlet in MpesaOutlet.objects.all():
        shift = outlet.sessions.filter(status=MpesaSession.OPEN).order_by("-opened_at").first()
        if shift:
            cash, electronic = session_balances(shift)
            rows.append({"key": f"agency-{outlet.pk}", "label": outlet.display_name, "amount": cash + electronic, "cash": cash, "float": electronic,
                         "state": "OPEN", "since": shift.opened_at, "opening_cash": shift.opening_cash, "opening_float": shift.opening_float})
            continue
        last = outlet.sessions.filter(status=MpesaSession.CLOSED, closing_cash_actual__isnull=False).order_by("-closed_at").first()
        if last:
            cash, electronic = last.closing_cash_actual, last.closing_float_actual or ZERO
            rows.append({"key": f"agency-{outlet.pk}", "label": outlet.display_name, "amount": cash + electronic, "cash": cash, "float": electronic,
                         "state": "CLOSED", "since": last.closed_at, "opening_cash": None, "opening_float": None})
    return rows


def _investments():
    from .investments import value
    from .models import Investment
    from .investment_interest import estimate
    rows = []
    for investment in Investment.objects.all():
        held = value(investment)
        if held:
            guess = estimate(investment)
            rows.append({"key": f"investment-{investment.pk}", "label": investment.name, "amount": held,
                         "estimated_interest": guess["net"] if guess else None})
    return rows


def _loans():
    from .loans import outstanding
    from .models import Loan
    return sum((outstanding(loan) for loan in Loan.objects.filter(cancelled_at__isnull=True)), ZERO)


def _unpaid_expenses():
    from .models import Expense
    from .services import expense_outstanding
    return sum((max(expense_outstanding(e), ZERO) for e in Expense.objects.all()), ZERO)


def _commission_due():
    from .models import JournalLine
    totals = JournalLine.objects.filter(account__code="1160").aggregate(d=Sum("debit"), c=Sum("credit"))
    return (totals["d"] or ZERO) - (totals["c"] or ZERO)


def snapshot(*, stock=None, receivables=None, payables=None, save=True):
    """The net worth now. ``stock``, ``receivables`` and ``payables`` are passed in by the dashboard (None = not allowed to see)."""
    shop, agency, investments = _shop_money(), _agency_money(), _investments()
    groups = [
        {"key": "money", "label": "Shop money (drawer, till, bank)", "side": "OWNS", "amount": sum((r["amount"] for r in shop), ZERO), "items": shop},
        {"key": "agency", "label": "M-Pesa agency cash and float", "side": "OWNS", "amount": sum((r["amount"] for r in agency), ZERO), "items": agency},
        {"key": "investments", "label": "Investments", "side": "OWNS", "amount": sum((r["amount"] for r in investments), ZERO), "items": investments},
        {"key": "loans", "label": "Money lent out", "side": "OWNS", "amount": _loans(), "items": []},
        {"key": "commission", "label": "Commission Safaricom still owes", "side": "OWNS", "amount": max(_commission_due(), ZERO), "items": []},
        {"key": "receivables", "label": "Customers owe you", "side": "OWNS", "amount": receivables, "items": []},
        {"key": "stock", "label": "Stock on the shelves (at cost)", "side": "OWNS", "amount": stock, "items": []},
        {"key": "payables", "label": "You owe suppliers", "side": "OWES", "amount": payables, "items": []},
        {"key": "expenses", "label": "Running costs not yet paid", "side": "OWES", "amount": _unpaid_expenses(), "items": []},
    ]
    left_out = [g["label"] for g in groups if g["amount"] is None]
    groups = [g for g in groups if g["amount"] is not None]
    owns = sum((g["amount"] for g in groups if g["side"] == "OWNS"), ZERO)
    owes = sum((g["amount"] for g in groups if g["side"] == "OWES"), ZERO)
    result = {"as_of": timezone.now(), "owns": owns, "owes": owes, "net_worth": owns - owes, "groups": groups, "left_out": left_out}
    if save and not left_out:
        _keep(result)
    result["history"] = history()
    return result


def _keep(result):
    """Today's figure, kept so the net worth can be followed over time; written only when it changed."""
    from .models import NetWorthSnapshot
    today = timezone.localdate()
    breakdown = {g["key"]: str(g["amount"]) for g in result["groups"]}
    current = NetWorthSnapshot.objects.filter(date=today).first()
    values = {"owns": result["owns"], "owes": result["owes"], "net_worth": result["net_worth"], "breakdown": breakdown}
    if current is None:
        NetWorthSnapshot.objects.create(date=today, **values)
    elif (current.owns, current.owes, current.breakdown) != (result["owns"], result["owes"], breakdown):
        NetWorthSnapshot.objects.filter(pk=current.pk).update(**values, updated_at=timezone.now())


def history(days=180):
    from .models import NetWorthSnapshot
    since = timezone.localdate() - timedelta(days=days)
    return [{"date": s.date, "owns": s.owns, "owes": s.owes, "net_worth": s.net_worth}
            for s in NetWorthSnapshot.objects.filter(date__gte=since).order_by("date")]
