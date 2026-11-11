"""Learning the commission M-KOPA pays for each phone and plan, from M-KOPA's own payments.

Each payment the owner records says which phones sold it covers. That is one fact: for example
4 × (X30, plan 1) + 2 × (X30, plan 2) = 7,800. Put together, the payments are a set of equations with one unknown per
plan, solved by least squares (the rates that best explain every payment, so a bonus or deduction in one payment is
evened out by the others). A plan's rate is learned only when the payments pin it down on its own: a plan that has
only ever been paid together with another, always in the same mix, cannot be told apart from it, so it keeps the rate
the owner typed until a payment separates them. All sums are exact fractions, so the same payments always teach the
same rates. Everything is worked out again from all payments after each one is recorded or undone.
"""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from django.utils import timezone

CENT = Decimal("0.01")


def _rank(rows):
    """The rank of a matrix of Fractions (rows of equal length), by Gaussian elimination."""
    rows = [list(row) for row in rows]
    rank, columns = 0, len(rows[0]) if rows else 0
    for column in range(columns):
        pivot = next((r for r in range(rank, len(rows)) if rows[r][column] != 0), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        for r in range(len(rows)):
            if r != rank and rows[r][column] != 0:
                factor = rows[r][column] / rows[rank][column]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[rank])]
        rank += 1
    return rank


def _least_squares(matrix, amounts):
    """One least-squares solution of matrix · x = amounts (free unknowns set to 0): solves the normal equations."""
    n = len(matrix[0])
    normal = [[sum(row[i] * row[j] for row in matrix) for j in range(n)] + [sum(row[i] * b for row, b in zip(matrix, amounts))] for i in range(n)]
    pivots, rank = [], 0
    for column in range(n):
        pivot = next((r for r in range(rank, n) if normal[r][column] != 0), None)
        if pivot is None:
            continue
        normal[rank], normal[pivot] = normal[pivot], normal[rank]
        lead = normal[rank][column]
        normal[rank] = [value / lead for value in normal[rank]]
        for r in range(n):
            if r != rank and normal[r][column] != 0:
                factor = normal[r][column]
                normal[r] = [a - factor * b for a, b in zip(normal[r], normal[rank])]
        pivots.append(column)
        rank += 1
    solution = [Fraction(0)] * n
    for row, column in enumerate(pivots):
        solution[column] = normal[row][n]
    return solution


def solve(payments):
    """{plan id: (rate, payments it was in)} for each plan the payments pin down. ``payments`` is a list of
    ({plan id: phones}, amount)."""
    plans = sorted({plan for counts, _ in payments for plan in counts})
    if not plans:
        return {}
    matrix = [[Fraction(counts.get(plan, 0)) for plan in plans] for counts, _ in payments]
    amounts = [Fraction(str(amount)) for _, amount in payments]
    solution = _least_squares(matrix, amounts)
    rank = _rank(matrix)
    learned = {}
    for index, plan in enumerate(plans):
        unit = [Fraction(1 if i == index else 0) for i in range(len(plans))]
        if _rank(matrix + [unit]) != rank:
            continue  # always paid in the same mix with another plan: its own rate cannot be known yet
        value = max(Decimal(solution[index].numerator) / Decimal(solution[index].denominator), Decimal("0"))
        learned[plan] = (value.quantize(CENT, rounding=ROUND_HALF_UP), sum(1 for counts, _ in payments if counts.get(plan)))
    return learned


def payment_equations():
    """One equation per payment of one total ({plan: phones}, amount), and one per phone when the owner gave what M-KOPA
    paid for each phone ({plan: 1}, its amount): those say each plan's commission outright."""
    from .models import MkopaCommission, MkopaSale
    counts, each = defaultdict(lambda: defaultdict(int)), []
    paid = MkopaSale.objects.filter(paid_by__reversed_at__isnull=True, paid_by__isnull=False)
    for payment, plan, itemised, received in paid.order_by("paid_by_id", "pk").values_list("paid_by_id", "plan_id", "paid_by__itemised", "commission_received"):
        if itemised:
            each.append(({plan: 1}, received or 0))
        else:
            counts[payment][plan] += 1
    amounts = dict(MkopaCommission.objects.filter(pk__in=counts).values_list("pk", "amount"))
    return [(dict(counts[pk]), amounts[pk]) for pk in sorted(counts)] + each


def learn():
    """Work out every plan's commission again from all the payments, and keep it on the plan."""
    from .models import MkopaPlan
    learned = solve(payment_equations())
    now = timezone.now()
    for plan in MkopaPlan.objects.all():
        value, used = learned.get(plan.pk, (None, 0))
        if (plan.learned_commission, plan.learned_from) != (value, used):
            MkopaPlan.objects.filter(pk=plan.pk).update(learned_commission=value, learned_from=used, learned_at=now if value is not None else None)
    return learned


def split(amount, sales):
    """How much of one payment was for each phone it covered: in proportion to each plan's rate as now known (evenly
    when no rate is known), so the parts add up to exactly what M-KOPA paid. {sale id: amount}."""
    amount = Decimal(str(amount))
    weights = {sale.pk: (sale.plan.rate if sale.plan.rate is not None else Decimal("0")) for sale in sales}
    total = sum(weights.values())
    if total <= 0:
        weights, total = {pk: Decimal("1") for pk in weights}, Decimal(len(weights))
    parts, given = {}, Decimal("0")
    ordered = sorted(weights)
    for pk in ordered[:-1]:
        parts[pk] = (amount * weights[pk] / total).quantize(CENT, rounding=ROUND_HALF_UP)
        given += parts[pk]
    if ordered:
        parts[ordered[-1]] = amount - given
    return parts
