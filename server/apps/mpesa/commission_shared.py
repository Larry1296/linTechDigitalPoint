"""The commission table shared by every agent business using the app.

Safaricom pays every agent the same commission for the same transaction at the same amount, so each business need not
learn the table on its own. What each business has measured (see commission_learning) is pooled into one table, and a
business uses it for any amount it has not learned itself.

Only the table is shared: a kind of transaction, an amount and what it earned. Never balances, transactions, customers
or which business measured what. A figure is trusted only when at least MIN_BUSINESSES different businesses agree on it,
at the same amount or at neighbouring amounts that earned the same, so one business's misread balance never spreads.
A business's own readings always come first: its own learned figures win, and where its own reading at an amount
disagrees with the shared table, the app asks again instead of using either.
"""
from collections import Counter, defaultdict

from django.core.cache import cache
from django.db.models.query import QuerySet

from .commission_learning import EARNING, Rates

MIN_BUSINESSES = 2
CACHE_KEY = "mpesa:shared-commission-table"
CACHE_SECONDS = 10 * 60


def _by_business():
    """{kind: {amount: {organization id: earned}}} — each business's latest measurement at each amount."""
    from apps.tenancy.context import branch_context, organization_context
    from .commission_learning import _history, _learn, latest_measurements
    from .models import MpesaOutlet
    found = defaultdict(lambda: defaultdict(dict))
    # Every business with an agent line; read one at a time, each inside its own business.
    for organization in sorted(set(QuerySet(MpesaOutlet).values_list("organization_id", flat=True))):
        with organization_context(organization), branch_context(None):
            outlets = _history()
            measured, _ = _learn(outlets)
            for (kind, amount), earned in latest_measurements(outlets, measured).items():
                found[kind][amount][organization] = earned
    return found


def build_table(found):
    """{kind: [(amount, earned, confirmed)]}: at each amount, what most businesses measured; confirmed when at least
    MIN_BUSINESSES agree there, or together with a neighbouring amount that earned the same."""
    table = {}
    for kind, amounts in found.items():
        points = []
        for amount in sorted(amounts):
            votes = Counter(amounts[amount].values()).most_common()
            if len(votes) > 1 and votes[0][1] == votes[1][1]:
                continue  # businesses disagree evenly: nothing to share at this amount
            earned = votes[0][0]
            points.append([amount, earned, {org for org, value in amounts[amount].items() if value == earned}])
        for i, point in enumerate(points):
            together = set(point[2])
            for j in (i - 1, i + 1):
                if 0 <= j < len(points) and points[j][1] == point[1]:
                    together |= points[j][2]
            point.append(len(together) >= MIN_BUSINESSES)
        table[kind] = [(amount, earned, confirmed) for amount, earned, _, confirmed in points]
    return table


def shared_rates():
    """The shared table as Rates; worked out again every few minutes."""
    table = cache.get(CACHE_KEY)
    if table is None:
        table = build_table(_by_business())
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

