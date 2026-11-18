"""Commission earned on each transaction, learned by the app from the commission balance the operator reads after it.

Safaricom adds a fixed commission after every deposit, withdrawal and airtime sale, the same for every amount within a
band (say 1,001-2,500). When a transaction's reading comes straight after the previous one's, the rise is exactly what
that transaction earned ("measured"). Every measurement teaches the app what that kind of transaction, at that amount,
earns. A transaction with no reading of its own is then filled in ("learned") when the app has seen the same amount, or
amounts on both sides of it that earned the same, so it must lie in their band. Anything else stays unknown rather than
guessed.

Safaricom's rates are not forever. Every rate is kept with the day it came into force, and each transaction is worked
out at the rate of its own day, so a new rate never changes what was earned before it. Once learned, the form asks for
a reading only now and then, at random, to check the rates still hold. Two such checks in a row that do not match, or
a year since the rates were last confirmed, start a check: the form asks after every transaction, a new figure read
twice becomes the new rate from the first of those readings, and five readings in a row that match end it (see
tariff_state).

Transactions in between without a reading are taken off at what the app already knows they earn, so it only needs
to ask for a reading while an amount is new to it. The reading taken when a shift opens, or any time during it, is a starting point
too, so the next transaction is measured from it. A reading lower than the one before
(Safaricom paid the commission out), or with a reversed or unknown transaction in between, measures nothing.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import MpesaSession, MpesaTransaction

EARNING = ("CUSTOMER_DEPOSIT", "CUSTOMER_WITHDRAWAL", "AIRTIME_SALE")
LABELS = {"CUSTOMER_DEPOSIT": "Deposits", "CUSTOMER_WITHDRAWAL": "Withdrawals", "AIRTIME_SALE": "Airtime"}
HISTORY_DAYS = 3 * 366  # long enough to hold the readings behind rates checked once a year
SUNDAY = 6  # the agency does not open on Sundays


class _Reading:
    """A commission balance read apart from any transaction (when a shift opened, or later in it): a starting point for
    the readings, not a transaction (``standing`` is False, so nothing counts it as one)."""
    pk, standing, start = None, False, True

    def __init__(self, session, done_at, balance):
        self.outlet_id, self.session_id, self.done_at, self.commission_balance = session.outlet_id, session.pk, done_at, balance


def _history(outlet_ids=None):
    """Each outlet's deposits, withdrawals and airtime sales in the order they were done on the line, with the readings
    taken apart from them (when each shift opened, or later in it). A correction takes the place of the entry it replaced; a reversed entry that was not
    corrected is kept as a break in the readings."""
    since = timezone.now() - timedelta(days=HISTORY_DAYS)
    rows = MpesaTransaction.objects.filter(transaction_type__in=EARNING, occurred_at__gte=since)
    openings = MpesaSession.objects.filter(opened_at__gte=since)
    if outlet_ids is not None:
        rows = rows.filter(outlet_id__in=outlet_ids)
        openings = openings.filter(outlet_id__in=outlet_ids)
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
    for session in openings.only("pk", "outlet_id", "opened_at", "opening_commission_balance", "commission_readings"):
        outlets[session.outlet_id] += [_Reading(session, at, balance) for at, balance in session.balance_readings()]
    for rows in outlets.values():
        rows.sort(key=lambda r: (r.done_at, 0 if getattr(r, "start", False) else 1, r.pk or 0))
    return outlets


def measure(outlets, rates=None):
    """What each transaction earned, from the rise since the previous reading: {id: amount}. Transactions in between
    without a reading are taken off at what ``rates`` says they earned; if any of them is not known, nothing is measured."""
    measured = {}
    for rows in outlets.values():
        last, between, broken = None, [], True
        for row in rows:
            if getattr(row, "start", False):
                last, between, broken = row.commission_balance, [], False  # a reading on its own: measure from it
                continue
            if not row.standing:
                broken = True  # a reversed transaction: what happened to its commission is not known
                continue
            if row.commission_balance is None:
                between.append(rates.predict(row.transaction_type, row.amount, row.done_at) if rates else None)
                continue
            known = None not in between
            if last is not None and not broken and known and row.commission_balance - last - sum(between) >= 0:
                measured[row.pk] = row.commission_balance - last - sum(between)
            last, between, broken = row.commission_balance, [], False
    return measured


RECHECK_DAYS = 365  # the rates are checked again a year after they were last confirmed: Safaricom's rates are not forever
CHECK_RUN = 5  # readings in a row that match the rates already known: Safaricom has not changed them, stop checking
CHANGE_SIGNS = 2  # spot checks in a row that do not match: Safaricom changed something, learn again
SPOT_GAP = (8, 20)  # a learned table is spot-checked once every 8 to 20 transactions, at random


def build_table(found):
    """{kind: [{"amount", "periods", "doubt"}]} by amount, from measurements {kind: {amount: [(moment, earned)]}},
    taking every reading in the order it was read.

    A figure read twice in a row at an amount is a rate, in force from the first of those readings until a different
    figure is confirmed (Safaricom changed its rates); each period is [from, earned, last seen on the line]. A reading
    of the rate in force sees it again. A figure read once is confirmed too when the neighbouring amount's latest
    figure is the same (both lie in one band; a neighbour read once is confirmed with it). Otherwise it is ``doubt``
    (moment, earned): a misread, or the first sign of a new rate."""
    table = {}
    for kind, amounts in found.items():
        points = {amount: {"amount": amount, "periods": [], "doubt": None} for amount in amounts}
        readings = sorted((at, amount, earned) for amount, rows in amounts.items() for at, earned in rows)
        seen = []
        for at, amount, value in readings:
            point = points[amount]
            if amount not in seen:
                seen.append(amount)
                seen.sort()
            periods, doubt = point["periods"], point["doubt"]
            if periods and value == periods[-1][1]:
                periods[-1][2], point["doubt"] = at, None
                continue
            if doubt and doubt[1] == value:
                periods.append([doubt[0], value, at])
                point["doubt"] = None
                continue
            i = seen.index(amount)
            neighbours = [points[seen[j]] for j in (i - 1, i + 1) if 0 <= j < len(seen)]
            agreeing = [n for n in neighbours if (n["doubt"] or (n["periods"][-1] if n["periods"] else None) or (None, None))[1] == value]
            if agreeing:
                periods.append([at, value, at])
                point["doubt"] = None
                for neighbour in agreeing:
                    if neighbour["doubt"]:
                        neighbour["periods"].append([neighbour["doubt"][0], value, neighbour["doubt"][0]])
                        neighbour["doubt"] = None
            else:
                point["doubt"] = (at, value)
        table[kind] = [points[amount] for amount in sorted(points)]
    return table


def is_due(checked, now=None):
    """Whether rates last confirmed at ``checked`` should be checked again (a year on)."""
    return checked is not None and (now or timezone.now()) - checked > timedelta(days=RECHECK_DAYS)


def known_before(points, value, at):
    """What the app knew an amount earned just before moment ``at``, from rates in force before then: at that amount,
    or between two amounts that earned the same. None if it did not know yet (a new amount is no check)."""
    def then(point):
        in_force = [period for period in point["periods"] if period[0] < at]
        return in_force[-1][1] if in_force else None
    exact = next((point for point in points if point["amount"] == value), None)
    if exact and then(exact) is not None:
        return then(exact)
    below = [point for point in points if point["amount"] < value]
    above = [point for point in points if point["amount"] > value]
    if below and above:
        low, high = then(below[-1]), then(above[0])
        if low is not None and low == high:
            return low
    return None


def tariff_state(found, table):
    """Whether Safaricom's rates as learned still hold, from every reading in the order it was taken. Each reading of
    an amount whose rate was already known is a check: it matches or it does not.

    "learned": the rates hold; the form asks only now and then (a spot check). Two spot checks in a row that do not
    match, whatever kinds and amounts, mean Safaricom changed something: "checking". So does a year since the rates
    were last confirmed. "checking": the form asks after every transaction and new figures are learned as usual; five
    readings in a row that match what the app knows (the old rates, or the new ones once learned) end it: "learned"
    again from then. One reading that does not match, then one that does, is a misread and changes nothing.
    {"mode", "reason" ("yearly" | "changed" | None), "confirmed" (moment), "matched" (in a row, while checking)}."""
    readings = sorted((at, kind, amount, earned) for kind, amounts in found.items() for amount, rows in amounts.items() for at, earned in rows)
    state = {"mode": "learned", "reason": None, "confirmed": readings[0][0] if readings else None, "matched": 0, "missed": 0}
    for at, kind, amount, earned in readings:
        if state["mode"] == "learned" and is_due(state["confirmed"], at):
            state.update(mode="checking", reason="yearly", matched=0, missed=0)
        expected = known_before(table.get(kind, []), amount, at)
        if expected is None:
            continue
        if earned == expected and state["mode"] == "checking":
            state["matched"] += 1
            if state["matched"] >= CHECK_RUN:
                state.update(mode="learned", reason=None, confirmed=at, matched=0)
        elif earned == expected:
            state["missed"] = 0
        elif state["mode"] == "checking":
            state["matched"] = 0
        else:
            state["missed"] += 1
            if state["missed"] >= CHANGE_SIGNS:
                state.update(mode="checking", reason="changed", matched=0, missed=0)
    return state


def state_now(state, now=None):
    """``state`` as it stands at ``now``: a year after the rates were last confirmed, they are being checked."""
    if state["mode"] == "learned" and is_due(state["confirmed"], now):
        return {**state, "mode": "checking", "reason": "yearly", "matched": 0}
    return state


def spot_check_due(outlet_id):
    """Whether the next transaction on this line is a spot check: once the number of transactions since the last
    commission reading reaches a gap of 8 to 20, picked at random from that reading (the same answer however often the
    form asks, and not a pattern the operator can see)."""
    readings = MpesaTransaction.objects.filter(outlet_id=outlet_id, transaction_type__in=EARNING)
    last = readings.filter(commission_balance__isnull=False).order_by("-occurred_at", "-pk").first()
    low, high = SPOT_GAP
    gap = low + (last.pk * 7919) % (high - low + 1) if last else low
    since = readings.filter(occurred_at__gt=last.occurred_at) if last else readings
    return since.count() >= gap


class Rates:
    """What the app has learned: for each kind of transaction and amount, the commission it earns and since when, so
    every transaction is worked out at the rate in force on its own day. A new rate from Safaricom starts a new period
    and never changes what transactions before it earned.

    A rate is trusted once it is confirmed: the same amount earned the same twice in a row, or a neighbouring amount
    earned the same. So one misread balance never becomes a rate. With ``doubt`` (a business's own readings), a
    different figure read once makes the app ask again for transactions after it; the shared table ignores it."""

    def __init__(self, outlets, measured, doubt=True):
        found = defaultdict(lambda: defaultdict(list))
        for rows in outlets.values():
            for row in rows:
                if row.pk in measured:
                    found[row.transaction_type][row.amount].append((row.done_at, measured[row.pk]))
        self.points, self.doubt = build_table(found), doubt

    @classmethod
    def from_points(cls, points, doubt=False):
        """Rates from a ready table (see build_table), e.g. the one shared by all agents."""
        rates = cls.__new__(cls)
        rates.points, rates.doubt = points, doubt
        return rates

    def figure(self, point, at=None):
        """What ``point``'s amount earned at moment ``at`` (now if not given): the rate in force then. Before its first
        rate was seen, the first rate (it was learned later, not changed)."""
        if point["doubt"] and self.doubt and (at is None or at >= point["doubt"][0]):
            return None
        periods = point["periods"]
        if not periods:
            return None
        if at is None:
            return periods[-1][1]
        in_force = [period for period in periods if period[0] <= at]
        return (in_force[-1] if in_force else periods[0])[1]

    def point(self, kind, value):
        return next((point for point in self.points.get(kind, []) if point["amount"] == value), None)

    @staticmethod
    def latest(point):
        """The figure last read at ``point``'s amount, confirmed or not."""
        return point["doubt"][1] if point["doubt"] else point["periods"][-1][1]

    def predict(self, kind, value, at=None):
        """The commission for ``value`` at moment ``at`` (now if not given): confirmed at that amount, or between two
        amounts that earned the same then."""
        exact = self.point(kind, value)
        if exact:
            return self.figure(exact, at)
        points = self.points.get(kind, [])
        below = [p for p in points if p["amount"] < value]
        above = [p for p in points if p["amount"] > value]
        if below and above:
            low, high = self.figure(below[-1], at), self.figure(above[0], at)
            if low is not None and low == high:
                return low
        return None

    def bands(self):
        """The learned table, as amount ranges that earn the same now: what the app knows, shown so it can be checked.
        A single amount not yet confirmed is shown too, marked, so it is clear the app will ask about it again. Each
        band says when its rate was last seen on the line, and since when it has been in force if Safaricom changed it."""
        rows = []
        for kind in EARNING:
            band = None
            for point in self.points.get(kind, []):
                confirmed = bool(point["periods"]) and not (self.doubt and point["doubt"])
                earned = point["periods"][-1][1] if confirmed else self.latest(point)
                checked = point["periods"][-1][2] if confirmed else None
                since = point["periods"][-1][0] if confirmed and len(point["periods"]) > 1 else None
                if band and band["earned"] == earned:
                    band["to"], band["seen"], band["confirmed"] = point["amount"], band["seen"] + 1, True
                    band["checked"] = max(filter(None, (band["checked"], checked)), default=None)
                    band["since"] = max(filter(None, (band["since"], since)), default=None)
                else:
                    band = {"kind": kind, "label": LABELS[kind], "from": point["amount"], "to": point["amount"], "earned": earned,
                            "seen": 1, "confirmed": confirmed, "checked": checked, "since": since}
                    rows.append(band)
        return rows


def _learn(outlets, shared=None):
    """Two passes: readings straight after each other teach the first rates, which then let readings with known
    transactions in between count too. With ``shared`` (the table every business has taught), transactions in between
    that the shared table knows count from the first reading too, so a new business measures from day one."""
    first = measure(outlets, shared)
    from .commission_shared import WithShared
    own = Rates(outlets, first)
    measured = measure(outlets, WithShared(own, shared) if shared is not None else own)
    return measured, Rates(outlets, measured)


def learn(outlet_ids=None):
    """The transactions, what was measured and the rates learned from all outlets' readings (the tariff is Safaricom's,
    the same everywhere), filled out with what other agents using the app have confirmed (see commission_shared)."""
    from .commission_shared import WithShared, shared_rates
    shared = shared_rates()
    outlets = _history(outlet_ids)
    if outlet_ids is None:
        measured, rates = _learn(outlets, shared)
    else:
        measured, _ = _learn(outlets, shared)
        rates = _learn(_history(), shared)[1]
    return outlets, measured, WithShared(rates, shared)


def advice(outlet_id, kind, value):
    """Whether to ask for the commission balance after a ``kind`` transaction of ``value``, and why:
    "new" — the app has not learned this amount; "yearly" / "changed" — the rates are being checked (a year since they
    were confirmed, or two spot checks in a row did not match), until five readings in a row match; "spot" — a random
    check that the learned rates still hold. Otherwise the box goes away and the commission is worked out by itself.
    ``matched`` says how many readings in a row have matched while checking."""
    from .commission_shared import tariff
    _, _, rates = learn([outlet_id])
    known = rates.predict(kind, value) if kind in EARNING else None
    state = state_now(tariff())
    reason = None
    if kind in EARNING and known is None:
        reason = "new"
    elif kind in EARNING and state["mode"] == "checking":
        reason = state["reason"]
    elif kind in EARNING and spot_check_due(outlet_id):
        reason = "spot"
    return {"earned": known, "ask": reason is not None, "reason": reason,
            "matched": state["matched"] if reason in ("yearly", "changed") else None, "needed": CHECK_RUN}


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
                value = rates.predict(row.transaction_type, row.amount, row.done_at)
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


def balance_now(outlet_id):
    """The outlet's commission balance now: the last balance read off the agent line, plus what every transaction since
    then earned as the app works it out (measured or learned), less commission recorded as paid out or used since then
    (Safaricom moves it out of the commission balance). A transaction it cannot work out yet adds nothing and is
    counted in ``unknown``, so the figure is never guessed. {"value", "read", "read_at", "worked_out", "paid_out", "unknown"}."""
    from .models import MpesaCommissionEntry
    outlets, measured, rates = learn([outlet_id])
    rows = outlets.get(outlet_id, [])
    last = max((i for i, row in enumerate(rows) if row.commission_balance is not None), default=None)
    if last is None:
        return {"value": None, "read": None, "read_at": None, "worked_out": Decimal("0"), "paid_out": Decimal("0"), "unknown": 0}
    since = [row for row in rows[last + 1:] if row.standing]
    totals = summary(since, earned(outlets, measured, rates))
    read, read_at = rows[last].commission_balance, rows[last].done_at
    paid_out = Decimal("0")
    for entry in MpesaCommissionEntry.objects.filter(outlet_id=outlet_id, reversed_at__isnull=True).select_related("opening_session"):
        # Paid between two shifts: the reading that shift opened with already shows it, so it is taken off only when
        # the shift opened after the last reading.
        moment = entry.opening_session.opened_at if entry.opening_session_id else entry.recognized_at
        if moment > read_at:
            paid_out += entry.amount
    value = max(Decimal("0"), read + totals["earned"] - paid_out)
    return {"value": value, "read": read, "read_at": read_at, "worked_out": totals["earned"], "paid_out": paid_out, "unknown": totals["unknown"]}


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


def forecast(as_of=None, learned=None):
    """The commission the month of ``as_of`` (now if not given) should bring, as it stood at that moment.

    So far: what the month's transactions earned up to then, measured or learned; any not worked out yet count at the
    average commission of those that were. Then the rest of the month at the same pace: the daily rate since the
    month's first transaction, times the days left until the month closes.
    """
    import calendar
    as_of = as_of or timezone.now()
    today = timezone.localtime(as_of).date()
    first = today.replace(day=1)
    last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    outlets, measured, rates = learned or learn()
    results = earned(outlets, measured, rates)
    rows = [r for rows in outlets.values() for r in rows if r.standing and first <= timezone.localtime(r.done_at).date() <= today and r.done_at <= as_of]
    totals = summary(rows, results)
    worked_out = totals["measured"] + totals["learned"]
    average = totals["earned"] / worked_out if worked_out else Decimal("0")
    so_far = totals["earned"] + average * totals["unknown"]
    began = min((timezone.localtime(r.done_at).date() for r in rows), default=today)
    working = lambda start, end: sum(1 for n in range((end - start).days + 1) if (start + timedelta(days=n)).weekday() != SUNDAY)
    daily = so_far / max(1, working(began, today))
    days_left = working(today + timedelta(days=1), last) if today < last else 0
    cents = lambda value: value.quantize(Decimal("0.01"))
    return {"month": first, "label": first.strftime("%B %Y"), "as_of": as_of, "so_far": cents(so_far), "daily": cents(daily),
            "days_left": days_left, "forecast": cents(so_far + daily * days_left), "transactions": len(rows), "unknown": totals["unknown"]}


def worked_out(start, end, learned=None):
    """Commission earned from day ``start`` to day ``end`` (both included), as the app works it out: measured or
    learned, and any transaction not worked out yet at the average of those that were."""
    outlets, measured, rates = learned or learn()
    results = earned(outlets, measured, rates)
    rows = [r for rows in outlets.values() for r in rows if r.standing and start <= timezone.localtime(r.done_at).date() <= end]
    totals = summary(rows, results)
    known = totals["measured"] + totals["learned"]
    average = totals["earned"] / known if known else Decimal("0")
    return (totals["earned"] + average * totals["unknown"]).quantize(Decimal("0.01"))


def unpaid(start, end):
    """Commission the agency earned between ``start`` and ``end`` in months Safaricom has not paid yet (nothing recorded
    for them), as the app works it out: income that is coming, not yet in the books. {"amount", "months"}."""
    from .models import MpesaCommissionEntry
    month, months, amount, learned = start.replace(day=1), [], Decimal("0"), None
    while month <= end:
        following = (month + timedelta(days=32)).replace(day=1)
        if not MpesaCommissionEntry.objects.filter(period=month, reversed_at__isnull=True).exists():
            learned = learned or learn()
            value = worked_out(max(start, month), min(end, following - timedelta(days=1)), learned)
            if value:
                amount += value
                months.append(month.strftime("%B %Y"))
        month = following
    return {"amount": amount, "months": months}
