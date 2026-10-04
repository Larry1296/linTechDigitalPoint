"""How a sale line's money is worked out. Used by counter sales and Cyber jobs alike.

    gross      = quantity × actual agreed unit price
    base       = gross − line discount
    tax        = base × rate / (1 + rate)   when prices include tax
               = base × rate                when tax is added on top
    net        = revenue that belongs to the business (excludes tax)
    payable    = what the customer owes for the line
    gross profit = net − COGS (from recorded cost layers only)

Tax is off unless a business configures it explicitly (Organization.settings["tax"]); no rate is assumed.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from rest_framework.exceptions import ValidationError

CENT = Decimal("0.01")


def cents(value):
    return Decimal(value).quantize(CENT, ROUND_HALF_UP)


def tax_config(organization):
    """{'enabled', 'name', 'rate' (a fraction such as 0.16), 'inclusive'} from the business's own settings."""
    raw = (organization.settings or {}).get("tax") or {}
    if not raw.get("enabled"):
        return {"enabled": False, "name": "", "rate": Decimal("0"), "inclusive": True}
    try:
        rate = Decimal(str(raw.get("rate")))
    except (InvalidOperation, TypeError):
        raise ValidationError("The business tax rate is not valid. Correct it in Settings before selling.")
    if not rate.is_finite() or rate < 0 or rate >= 1:
        raise ValidationError("The business tax rate must be between 0 and 1 (for example 0.16 for 16%).")
    return {"enabled": True, "name": str(raw.get("name") or "Tax"), "rate": rate, "inclusive": bool(raw.get("inclusive", True))}


def allocate_by_value(values, amount):
    """Splits an amount across lines in proportion to their value; the last line takes the rounding remainder."""
    amount = cents(amount)
    total = sum(values, Decimal("0"))
    shares, remaining = [], amount
    for index, value in enumerate(values):
        share = remaining if index == len(values) - 1 else (cents(amount * value / total) if total else Decimal("0"))
        shares.append(share)
        remaining -= share
    return shares


def spread_discount(grosses, discount):
    """Splits a whole-sale discount across lines by value; a discount can never exceed what is being sold."""
    discount = cents(discount)
    if discount < 0:
        raise ValidationError("Discount cannot be negative.")
    if discount > sum(grosses, Decimal("0")):
        raise ValidationError("Discount cannot exceed the subtotal.")
    return allocate_by_value(grosses, discount)


def price_line(quantity, unit_price, discount, tax):
    gross = cents(quantity * unit_price)
    discount = cents(discount)
    if discount < 0 or discount > gross:
        raise ValidationError("A line discount must be between zero and the line amount.")
    base = gross - discount
    if not tax["enabled"] or not tax["rate"]:
        return {"gross": gross, "discount": discount, "tax": Decimal("0"), "net": base, "payable": base}
    if tax["inclusive"]:
        tax_amount = cents(base * tax["rate"] / (1 + tax["rate"]))
        return {"gross": gross, "discount": discount, "tax": tax_amount, "net": base - tax_amount, "payable": base}
    tax_amount = cents(base * tax["rate"])
    return {"gross": gross, "discount": discount, "tax": tax_amount, "net": base, "payable": base + tax_amount}
