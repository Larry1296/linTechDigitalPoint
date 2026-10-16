"""Once Safaricom has paid a month's commission: what the app worked out for that month set against what was paid, the
likely reasons for any difference, and what to do so the next months come out closer.

The app's figure for a month has three parts: commission measured from a reading straight after a transaction (exact),
commission learned for amounts it has seen before (right unless Safaricom changed its rates), and transactions it could
not work out, counted at the month's average (a guess). The reasons look at each part and at the readings themselves:
a reading taken apart from a transaction (when a shift opened, or during it) that does not match what the app expected
shows commission the transactions in the app do not explain, most often transactions done on the line but not entered.
Nothing here changes the books; it only explains.

When Safaricom has paid the same share of the app's figure for a few months in a row (say about 90%, after a tax), the
forecast for the month in progress expects that share too (``payout_share``).
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .commission_learning import LABELS, earned, learn

ZERO = Decimal("0")
CLOSE = Decimal("0.5")  # under half a shilling is the same


def _cents(value):
    return value.quantize(Decimal("0.01"))


def _day(row):
    return timezone.localtime(row.done_at).date()


def _readings_gap(outlets, results, first, last, payouts):
    """Readings in the month taken apart from a transaction, set against what the app expected them to be: the last
    reading plus what every transaction since earned. (rose_more, rose_less, count): how much more, and how much less,
    the balance rose than the app's transactions explain, over how many readings. A reading lower than the one before
    (Safaricom paid the commission out), an unknown or reversed transaction in between, or commission recorded as paid
    out in between, compares nothing."""
    more = less = ZERO
    count = 0
    for rows in outlets.values():
        last_value = last_at = None
        since, broken = ZERO, True
        for row in rows:
            start = getattr(row, "start", False)
            if not start:
                if not row.standing:
                    broken = True
                    continue
                value = results.get(row.pk, (None, None))[0]
                if value is None:
                    broken = True
                else:
                    since += value
                if row.commission_balance is None:
                    continue
            if start and last_value is not None and not broken and first <= _day(row) <= last and row.commission_balance >= last_value \
                    and not any(last_at < moment <= row.done_at for moment in payouts.get(row.outlet_id, [])):
                gap = row.commission_balance - (last_value + since)
                if abs(gap) >= CLOSE:
                    count += 1
                    if gap > 0:
                        more += gap
                    else:
                        less -= gap
            last_value, last_at, since, broken = row.commission_balance, row.done_at, ZERO, False
    return more, less, count


def _payouts():
    """{outlet id: [moments]} when commission recorded as paid out left the commission balance."""
    from .models import MpesaCommissionEntry
    moments = {}
    for entry in MpesaCommissionEntry.objects.filter(reversed_at__isnull=True).select_related("opening_session"):
        moment = entry.opening_session.opened_at if entry.opening_session_id else entry.recognized_at
        moments.setdefault(entry.outlet_id, []).append(moment)
    return moments


def _rate_changes(outlets, measured, first, last):
    """Amounts measured in the month that earned something different from what the same amount earned before it:
    Safaricom's rates may have changed. [label]."""
    seen, changed = {}, []
    for rows in outlets.values():
        for row in sorted((r for r in rows if r.pk in measured), key=lambda r: r.done_at):
            key = (row.transaction_type, row.amount)
            before = seen.get(key)
            if before is not None and before != measured[row.pk] and first <= _day(row) <= last:
                label = f"{LABELS[row.transaction_type].lower()} of {row.amount:,.0f}"
                if label not in changed:
                    changed.append(label)
            seen[key] = measured[row.pk]
    return changed


def check(month, paid, learned=None):
    """The comparison for ``month`` (its first day) with ``paid`` (what Safaricom paid for it): the parts of the app's
    figure, the difference, the likely reasons and what to do. None when nothing is paid yet."""
    if paid is None:
        return None
    outlets, measured, rates = learned or learn()
    results = earned(outlets, measured, rates)
    following = (month + timedelta(days=32)).replace(day=1)
    last = following - timedelta(days=1)
    rows = [r for rows in outlets.values() for r in rows if not getattr(r, "start", False) and month <= _day(r) <= last]
    standing = [r for r in rows if r.standing]
    parts = {"measured": [ZERO, 0], "learned": [ZERO, 0], "unknown": [ZERO, 0]}
    for row in standing:
        value, source = results.get(row.pk, (None, None))
        part = parts[source or "unknown"]
        part[0] += value or ZERO
        part[1] += 1
    known = parts["measured"][1] + parts["learned"][1]
    average = (parts["measured"][0] + parts["learned"][0]) / known if known else ZERO
    guessed = average * parts["unknown"][1]
    worked = _cents(parts["measured"][0] + parts["learned"][0] + guessed)
    paid = Decimal(str(paid))
    difference = paid - worked
    more, less, gaps = _readings_gap(outlets, results, month, last, _payouts())
    changed = _rate_changes(outlets, measured, month, last)
    edge = lambda day: sum((results[r.pk][0] or ZERO for rows in outlets.values() for r in rows
                            if not getattr(r, "start", False) and r.standing and _day(r) == day and r.pk in results), ZERO)
    reasons, advice = [], []
    same = abs(difference) < CLOSE

    if more >= CLOSE:
        reasons.append({"key": "not_entered", "amount": _cents(more),
                        "text": f"The commission balance rose {more:,.2f} more than the transactions in the app explain ({gaps} "
                                f"{'reading' if gaps == 1 else 'readings'}). Most often that is deposits, withdrawals or airtime done on the "
                                "line but not entered in the app, so the app's figure is low by about that much."})
        advice.append("Enter every deposit, withdrawal and airtime sale done on the agent line, including any done before the shift was "
                      "opened in the app or after it was closed.")
    if less >= CLOSE:
        reasons.append({"key": "rose_less", "amount": _cents(less),
                        "text": f"The commission balance rose {less:,.2f} less than the app expected. A rate it learned may be too high, a "
                                "transaction may be entered that was not done on the line, or commission left the balance without being recorded."})
        advice.append("Check that every transaction in the app was really done on the line, and record any commission Safaricom paid out.")
    if parts["unknown"][1]:
        reasons.append({"key": "guessed", "amount": _cents(guessed),
                        "text": f"{parts['unknown'][1]} {'transaction' if parts['unknown'][1] == 1 else 'transactions'} could not be worked out "
                                f"and were counted at the month's average of {average:,.2f} each ({guessed:,.2f} in all). That part is a guess."})
        advice.append("When the app asks for the commission balance after a transaction, read it off the agent line and enter it: "
                      "that is how it learns new amounts.")
    if changed:
        reasons.append({"key": "rates_changed", "amount": None,
                        "text": f"Safaricom's rates seem to have changed during the month: {', '.join(changed[:5])} earned something "
                                "different from before. Commission worked out from the old rate before the change was noticed is off."})
        advice.append("For a few days after a rate change, enter the commission balance after each transaction so the app learns the new rates.")
    share = paid / worked if worked else None
    if share is not None and not same and Decimal("0.88") <= share <= Decimal("0.92"):
        reasons.append({"key": "tax", "amount": _cents(-difference),
                        "text": f"Safaricom paid about {share * 100:.0f}% of the app's figure. A cut of about 10% is usually withholding tax "
                                "Safaricom takes off before paying; the commission statement from Safaricom shows it."})
    last_day, next_day = edge(last), edge(following)
    if difference < 0 and last_day and abs(abs(difference) - last_day) <= last_day * Decimal("0.2"):
        reasons.append({"key": "month_end", "amount": _cents(last_day),
                        "text": f"The difference is close to the {last_day:,.2f} earned on {last:%d %B}. Safaricom may count that day, or "
                                "its late transactions, in the next month."})
    if difference > 0 and next_day and abs(difference - next_day) <= next_day * Decimal("0.2"):
        reasons.append({"key": "month_start", "amount": _cents(next_day),
                        "text": f"The difference is close to the {next_day:,.2f} earned on {following:%d %B}. Safaricom may have counted that "
                                "day in this month."})
    if parts["learned"][1] and (parts["measured"][1] * 2 < len(standing)):
        advice.append("Read the commission balance at least once in every shift (press Record commission balance, best just before "
                      "closing) so the app can check its learned rates against the line.")
    reversed_count = len(rows) - len(standing)
    if reversed_count:
        advice.append(f"{reversed_count} {'transaction was' if reversed_count == 1 else 'transactions were'} reversed this month; enter the "
                      "commission balance after the next transaction so the readings carry on from there.")
    if not same and not reasons:
        reasons.append({"key": "unexplained", "amount": None,
                        "text": "The readings do not show where the difference came from. Compare with Safaricom's commission statement for the month."})
    if same:
        advice = advice or ["The app's figure matched what Safaricom paid. Keep reading the balance as you do now."]
    return {"worked_out": worked, "paid": _cents(paid), "difference": _cents(difference), "same": same,
            "measured": {"amount": _cents(parts["measured"][0]), "count": parts["measured"][1]},
            "learned": {"amount": _cents(parts["learned"][0]), "count": parts["learned"][1]},
            "guessed": {"amount": _cents(guessed), "count": parts["unknown"][1]},
            "reversed": reversed_count, "reasons": reasons, "advice": list(dict.fromkeys(advice))}


def payout_share(rows):
    """What share of the app's figure Safaricom has paid, when the last paid months (two or three, newest first in
    ``rows``) agree within 3 points and it is not about all of it: a steady cut such as a tax. Else None."""
    shares = [Decimal(str(row["paid"])) / Decimal(str(row["expected"])) for row in rows
              if not row["current"] and row["paid"] is not None and Decimal(str(row["expected"])) > 0][:3]
    if len(shares) < 2 or max(shares) - min(shares) > Decimal("0.03"):
        return None
    share = sum(shares) / len(shares)
    return None if abs(share - 1) < Decimal("0.01") else share.quantize(Decimal("0.001"))
