"""Sharing a running cost between the parts of the business.

Rent, electricity or a guard serve the shop, the cyber and the M-Pesa agency together. The owner says how the cost is
shared, and each part's profit carries its share, so the parts' contributions still add up to the whole business's
profit. The cost is booked once in the books either way; only the per-part view divides it.

- INCOME: by what each part earned over the last 30 days (sales for the shop and services, commission for M-Pesa).
- EVEN: the same amount for every part.
- AMOUNTS: the owner enters each part's share; together they must make the whole amount.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .money_mode import business_parts, has_parts, part_names

CENT = Decimal("0.01")
INCOME, EVEN, AMOUNTS = "INCOME", "EVEN", "AMOUNTS"
INCOME_DAYS = 30


def divide(amount, weights):
    """Split amount (in cents) in proportion to weights; the cents left over go to the largest remainders."""
    total = sum(weights.values())
    raw = {key: amount * weight / total for key, weight in weights.items()}
    shares = {key: value.quantize(CENT, rounding=ROUND_DOWN) for key, value in raw.items()}
    left = int((amount - sum(shares.values())) / CENT)
    for key in sorted(raw, key=lambda k: raw[k] - shares[k], reverse=True)[:left]:
        shares[key] += CENT
    return shares


def income_by_part(days=INCOME_DAYS, today=None):
    """What each part earned over the last ``days`` days, from the books."""
    from apps.inventory.dashboard import pnl_rows
    today = today or timezone.localdate()
    earned = {}
    for row in pnl_rows(today - timedelta(days=days - 1), today):
        if row["field"] == "revenue":
            earned[row["unit"]] = earned.get(row["unit"], Decimal("0")) + row["amount"]
    return earned


def split(amount, how, entered=None):
    """{part: "amount"} for each part that carries some of the cost ({} when no split was asked for)."""
    if not how:
        return {}
    if not has_parts():
        raise ValidationError({"split": "Only a business with separate parts can share a cost between them."})
    parts = business_parts()
    amount = Decimal(str(amount)).quantize(CENT)
    if how == EVEN:
        shares = divide(amount, {part: Decimal("1") for part in parts})
    elif how == INCOME:
        earned = {part: max(value, Decimal("0")) for part, value in income_by_part().items() if part in parts}
        if not sum(earned.values()):
            raise ValidationError({"split": f"No part has earned anything in the last {INCOME_DAYS} days to share by. "
                                            "Share it evenly or enter each part's amount."})
        shares = divide(amount, earned)
    else:
        names = part_names()
        shares = {}
        for part, value in (entered or {}).items():
            if part not in parts:
                raise ValidationError({"shares": f"{names.get(part, part)} is not a part of this business."})
            try:
                value = Decimal(str(value or 0)).quantize(CENT)
            except Exception:
                raise ValidationError({"shares": f"Enter {names[part]}'s share as an amount."})
            if not value.is_finite() or value < 0:
                raise ValidationError({"shares": f"{names[part]}'s share cannot be below zero."})
            shares[part] = value
        if sum(shares.values()) != amount:
            raise ValidationError({"shares": f"The parts' shares add up to {sum(shares.values()):,.2f}; they must make the whole "
                                             f"{amount:,.2f}."})
    return {part: str(value) for part, value in shares.items() if value > 0}


def main_part(shares, fallback):
    """The part that carries most of a shared cost: its money pays when all the money is kept together."""
    return max(shares, key=lambda part: Decimal(shares[part])) if shares else fallback
