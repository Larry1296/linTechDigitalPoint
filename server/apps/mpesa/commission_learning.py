"""Commission earned on each transaction, learned by the app from the commission balance the operator reads after it.

Safaricom adds a fixed commission after every deposit, withdrawal and airtime sale, the same for every amount within a
band (say 1,001-2,500). When a transaction's reading comes straight after the previous one's, the rise is exactly what
that transaction earned ("measured"). Every measurement teaches the app what that kind of transaction, at that amount,
earns. A transaction with no reading of its own is then filled in ("learned") when the app has seen the same amount, or
amounts on both sides of it that earned the same, so it must lie in their band. Anything else stays unknown rather than
guessed. Newer measurements win, so a change in Safaricom's rates is picked up by itself.

Transactions in between without a reading are taken off at what the app already knows they earn, so it only needs
to ask for a reading when an amount is new to it (and now and then as a check). A reading lower than the one before
(Safaricom paid the commission out), or with a reversed or unknown transaction in between, measures nothing.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import MpesaTransaction

EARNING = ("CUSTOMER_DEPOSIT", "CUSTOMER_WITHDRAWAL", "AIRTIME_SALE")
LABELS = {"CUSTOMER_DEPOSIT": "Deposits", "CUSTOMER_WITHDRAWAL": "Withdrawals", "AIRTIME_SALE": "Airtime"}
HISTORY_DAYS = 400


def _history(outlet_ids=None):
    """Each outlet's deposits, withdrawals and airtime sales in the order they were done on the line. A correction takes
    the place of the entry it replaced; a reversed entry that was not corrected is kept as a break in the readings."""
    rows = MpesaTransaction.objects.filter(transaction_type__in=EARNING, occurred_at__gte=timezone.now() - timedelta(days=HISTORY_DAYS))
    if outlet_ids is not None:
        rows = rows.filter(outlet_id__in=outlet_ids)
    rows = list(rows.only("pk", "outlet_id", "session_id", "transaction_type", "amount", "commission_balance", "occurred_at", "corrects_id"))
    reversed_ids = set(MpesaTransaction.objects.filter(reversal_of__in=[r.pk for r in rows]).values_list("reversal_of_id", flat=True))
    by_id = {r.pk: r for r in rows}

    def done_at(row):
        while row.corrects_id and row.corrects_id in by_id:
            row = by_id[row.corrects_id]
        return row.occurred_at

    corrected = {r.corrects_id for r in rows if r.corrects_id}
    outlets = defaultdict(list)
    for row in sorted(rows, key=lambda r: (done_at(r), r.pk)):
        if row.pk in corrected:
            continue  # replaced by its correction, which stands in its place
        row.done_at, row.standing = done_at(row), row.pk not in reversed_ids
        outlets[row.outlet_id].append(row)
    return outlets


def measure(outlets, rates=None):
    """What each transaction earned, from the rise since the previous reading: {id: amount}. Transactions in between
    without a reading are taken off at what ``rates`` says they earned; if any of them is not known, nothing is measured."""
    measured = {}
    for rows in outlets.values():
        last, between, broken = None, [], True
        for row in rows:
            if not row.standing:
                broken = True  # a reversed transaction: what happened to its commission is not known
                continue
            if row.commission_balance is None:
                between.append(rates.predict(row.transaction_type, row.amount) if rates else None)
                continue
            known = None not in between
            if last is not None and not broken and known and row.commission_balance - last - sum(between) >= 0:
                measured[row.pk] = row.commission_balance - last - sum(between)
            last, between, broken = row.commission_balance, [], False
    return measured


class Rates:
    """What the app has learned: for each kind of transaction, the latest commission measured at each amount."""

    def __init__(self, outlets, measured):
        seen = defaultdict(dict)
        for rows in outlets.values():
            for row in rows:
                if row.pk in measured:
                    seen[row.transaction_type][row.amount] = (row.done_at, measured[row.pk])
        merged = {}
        for kind, amounts in seen.items():
            merged[kind] = sorted((value, earned) for value, (_, earned) in amounts.items())
        self.points = merged

    def predict(self, kind, value):
        """The commission for ``value``: measured at that amount, or between two amounts that earned the same."""
        points = self.points.get(kind, [])
        below = [p for p in points if p[0] <= value]
        above = [p for p in points if p[0] >= value]
        if below and below[-1][0] == value:
            return below[-1][1]
        if below and above and below[-1][1] == above[0][1]:
            return below[-1][1]
        return None

    def bands(self):
        """The learned table, as amount ranges that earned the same: what the app knows, shown so it can be checked."""
        rows = []
        for kind in EARNING:
            band = None
            for value, earned in self.points.get(kind, []):
                if band and band["earned"] == earned:
                    band["to"], band["seen"] = value, band["seen"] + 1
                else:
                    band = {"kind": kind, "label": LABELS[kind], "from": value, "to": value, "earned": earned, "seen": 1}
                    rows.append(band)
        return rows


def _learn(outlets):
    """Two passes: readings straight after each other teach the first rates, which then let readings with known
    transactions in between count too."""
    first = measure(outlets)
    measured = measure(outlets, Rates(outlets, first))
    return measured, Rates(outlets, measured)


def learn(outlet_ids=None):
    """The transactions, what was measured and the rates learned from all outlets' readings (the tariff is Safaricom's, the same everywhere)."""
    outlets = _history(outlet_ids)
    if outlet_ids is None:
        return (outlets, *_learn(outlets))
    measured, _ = _learn(outlets)
    return outlets, measured, _learn(_history())[1]


CHECK_EVERY = 20


def advice(outlet_id, kind, value):
    """Whether to ask for the commission balance after a ``kind`` transaction of ``value``: when the app has not
    learned that amount yet, and now and then as a check that Safaricom's rates have not changed."""
    outlets, _, rates = learn([outlet_id])
    known = rates.predict(kind, value) if kind in EARNING else None
    rows = [row for row in outlets.get(outlet_id, []) if row.standing]
    unread = 0
    for row in reversed(rows):
        if row.commission_balance is not None:
            break
        unread += 1
    reason = None
    if kind in EARNING and known is None:
        reason = "new"
    elif kind in EARNING and unread >= CHECK_EVERY:
        reason = "check"
    return {"earned": known, "ask": reason is not None, "reason": reason}


def earned(outlets, measured, rates):
    """{id: (amount or None, "measured" | "learned" | None)} for every standing transaction."""
    result = {}
    for rows in outlets.values():
        for row in rows:
            if not row.standing:
                continue
            if row.pk in measured:
                result[row.pk] = (measured[row.pk], "measured")
            else:
                value = rates.predict(row.transaction_type, row.amount)
                result[row.pk] = (value, "learned" if value is not None else None)
    return result


def summary(rows, results):
    """Total commission earned on ``rows`` (standing transactions), and how many of them it could not work out yet."""
    total, counts = Decimal("0"), {"measured": 0, "learned": 0, "unknown": 0}
    for row in rows:
        value, source = results.get(row.pk, (None, None))
        if value is None:
            counts["unknown"] += 1
        else:
            total += value
            counts[source] += 1
    return {"earned": total, **counts}


def for_shift(session):
    outlets, measured, rates = learn([session.outlet_id])
    results = earned(outlets, measured, rates)
    rows = [r for r in outlets.get(session.outlet_id, []) if r.standing and r.session_id == session.pk]
    return summary(rows, results)


def for_month(start, end):
    """Commission earned on every outlet's transactions done from ``start`` up to, not including, ``end`` (moments)."""
    outlets, measured, rates = learn()
    results = earned(outlets, measured, rates)
    rows = [r for rows in outlets.values() for r in rows if r.standing and start <= r.done_at < end]
    return summary(rows, results)
