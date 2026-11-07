"""The one commission table every agent business using the app teaches and uses.

Safaricom pays every agent the same commission for the same transaction at the same amount, so the app learns one table
for everybody: every business's measured commissions (see commission_learning) go into it, and every business uses it
for any amount it has not learned itself. A new business starts with everything the others have taught.

Only the table is shared: a kind of transaction, an amount and what it earned. Never balances, transactions, customers
or which business measured what. It is trusted by the same rule as a business's own readings, wherever they came from:
an amount that earned the same twice in a row, or next to an amount that earned the same. Once an amount is confirmed it
stays so until a different figure is confirmed there (Safaricom changed its rates), so one misread balance anywhere never
spreads or undoes what is known. A business's own readings come first: its own learned figures win, and where its own
reading at an amount disagrees with the shared table, the app asks again instead of using either.
"""
from collections import defaultdict

from django.core.cache import cache
from django.db.models.query import QuerySet

from .commission_learning import EARNING, Rates, confirm_neighbours

CACHE_KEY = "mpesa:shared-commission-table"
CACHE_SECONDS = 10 * 60


def _pooled():
    """{kind: {amount: [(done at, earned)]}} — every measurement made by every business. Two passes, like a business's
    own learning: what the businesses measured on their own makes a first table, which then lets readings with
    transactions in between that only the table knows count too (a new business's first readings, say)."""
    from apps.tenancy.context import branch_context, organization_context
    from .commission_learning import _history, _learn
    from .models import MpesaOutlet
    histories = []
    # Every business with an agent line; read one at a time, each inside its own business.
    for organization in sorted(set(QuerySet(MpesaOutlet).values_list("organization_id", flat=True))):
        with organization_context(organization), branch_context(None):
            histories.append(_history())

    def pool(shared=None):
        found = defaultdict(lambda: defaultdict(list))
        for outlets in histories:
            measured, _ = _learn(outlets, shared)
            for rows in outlets.values():
                for row in rows:
                    if row.pk in measured:
                        found[row.transaction_type][row.amount].append((row.done_at, measured[row.pk]))
        return found

    return pool(Rates.from_points(build_table(pool())))


def _settled(readings):
    """(earned, confirmed) at one amount: the newest figure read twice in a row, or else the latest reading, unconfirmed."""
    readings = [earned for _, earned in sorted(readings, key=lambda reading: reading[0])]
    for i in range(len(readings) - 1, 0, -1):
        if readings[i] == readings[i - 1]:
            return readings[i], True
    return readings[-1], False


def build_table(found):
    """{kind: [(amount, earned, confirmed)]} from every business's measurements together."""
    return {kind: confirm_neighbours([[amount, *_settled(amounts[amount])] for amount in sorted(amounts)])
            for kind, amounts in found.items()}


def shared_rates():
    """The shared table as Rates; worked out again every few minutes."""
    table = cache.get(CACHE_KEY)
    if table is None:
        table = build_table(_pooled())
        cache.set(CACHE_KEY, table, CACHE_SECONDS)
    return Rates.from_points(table)


def forget(instance=None, **_):
    """Work the shared table out again on next use once a new commission reading is saved. Other changes (an unread
    transaction in between, a reversal) show within CACHE_SECONDS."""
    if getattr(instance, "commission_balance", True) is not None:
        cache.delete(CACHE_KEY)


class WithShared:
    """A business's own rates, filled out with the shared table where it has not learned an amount itself."""

    def __init__(self, own, shared):
        self.own, self.shared = own, shared
        self.points = own.points  # what this business measured itself; its own readings decide measuring

    def predict(self, kind, value):
        mine = self.own.predict(kind, value)
        if mine is not None:
            return mine
        theirs = self.shared.predict(kind, value)
        exact = [point for point in self.own.points.get(kind, []) if point[0] == value]
        if exact and exact[0][1] != theirs:
            return None  # this business read something else here: ask again rather than choose
        return theirs

    def bands(self):
        """This business's learned table, then the shared ranges it has not learned itself, marked as shared."""
        own = self.own.bands()
        covered = defaultdict(list)
        for band in own:
            covered[band["kind"]].append((band["from"], band["to"]))
        extra = [{**band, "shared": True} for band in self.shared.bands() if band["confirmed"]
                 and not any(start <= band["to"] and band["from"] <= end for start, end in covered[band["kind"]])]
        order = {kind: i for i, kind in enumerate(EARNING)}
        return sorted(own + extra, key=lambda band: (order[band["kind"]], band["from"]))

