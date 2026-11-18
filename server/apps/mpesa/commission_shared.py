"""The one commission table every agent business using the app teaches and uses.

Safaricom pays every agent the same commission for the same transaction at the same amount, so the app learns one table
for everybody: every business's measured commissions (see commission_learning) go into it, and every business uses it
for any amount it has not learned itself. A new business starts with everything the others have taught.

Only the table is shared: a kind of transaction, an amount and what it earned. Never balances, transactions, customers
or which business measured what. It is trusted by the same rule as a business's own readings, wherever they came from:
an amount that earned the same twice in a row, or next to an amount that earned the same. Once an amount is confirmed it
stays so until a different figure is confirmed there (Safaricom changed its rates, which starts a new period and leaves
earlier transactions at the old rate), so one misread balance anywhere never spreads or undoes what is known. A reading
by any business checks the rates for everybody: whether they still hold or are being checked is one state for all. A business's own readings come first: its own learned figures win, and where its own
reading at an amount disagrees with the shared table, the app asks again instead of using either.
"""
from collections import defaultdict

from django.core.cache import cache
from django.db.models.query import QuerySet

from .commission_learning import EARNING, Rates, build_table, tariff_state

CACHE_KEY = "mpesa:shared-commission-table:v3"  # v3: rates kept with the day they came into force, and the check state
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


def _worked_out():
    """{"table", "state"}: the shared table and whether its rates still hold (one state for every agent, since the
    rates are Safaricom's); worked out again every few minutes and after every new reading."""
    found = cache.get(CACHE_KEY)
    if found is None:
        pooled = _pooled()
        table = build_table(pooled)
        found = {"table": table, "state": tariff_state(pooled, table)}
        cache.set(CACHE_KEY, found, CACHE_SECONDS)
    return found


def shared_rates():
    """The shared table as Rates."""
    return Rates.from_points(_worked_out()["table"])


def tariff():
    """Whether the learned rates still hold or are being checked (see commission_learning.tariff_state)."""
    return _worked_out()["state"]


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

    def predict(self, kind, value, at=None):
        mine = self.own.predict(kind, value, at)
        if mine is not None:
            return mine
        theirs = self.shared.predict(kind, value, at)
        exact = self.own.point(kind, value)
        if exact and self.own.latest(exact) != theirs:
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

