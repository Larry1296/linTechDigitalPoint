"""Checks an AI answer's money figures against the records it was given, before the business sees it.

The AI model may explain and summarise, but every money amount it writes must come from a tool result in the same
answer: the figure itself, or (as people add two lines up on paper) the sum or difference of two of them. This is a
plain number check, never another AI's opinion. An answer quoting an amount found nowhere in the records is not
shown: the business gets the answer worked out from the records instead (business_chat), and the mismatch is logged.
"""
import json
import re
from decimal import Decimal, InvalidOperation

# Questions about how money was made or spent: their answers are held back until their figures are checked.
FINANCIAL = re.compile(r"\b(profits?|loss(es)?|p&l|p ?and ?l|margins?|net|gross|revenue|income|earn(ed|ings|t)?|made|make|expenses?|"
                       r"costs?|cogs|turnover|takings|attain(ed)?|reach(ed)?|reconcile|add up|breakdown|dashboard|kes|ksh)\b", re.I)
# "KES 1,250", "KSh 1,250.50", "Sh. 300" (and the business's own currency code).
MONEY = r"\b(?:{codes})\.?\s*(-?\s?\d[\d,]*(?:\.\d+)?)"
MAX_PAIRS = 600  # numbers above this many: only single figures are matched (pairs would match almost anything)


def is_financial(question):
    return bool(FINANCIAL.search(question or ""))


def _walk(value, out):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(Decimal(str(value)))
    elif isinstance(value, str):
        try:
            out.add(Decimal(value.replace(",", "")))
        except (InvalidOperation, ValueError):
            pass
    elif isinstance(value, dict):
        for item in value.values():
            _walk(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, out)


def numbers_in(results):
    """Every number in the tool results (JSON texts; a result cut short is read for its numbers as text)."""
    found = set()
    for text in results:
        try:
            _walk(json.loads(text), found)
        except ValueError:
            for raw in re.findall(r"-?\d+(?:\.\d+)?", text):
                found.add(Decimal(raw))
    return found


def money_claims(answer, currency="KES"):
    codes = "|".join(sorted({re.escape(c) for c in (currency or "KES", "KES", "KSh", "Ksh", "KShs", "Sh")}, key=len, reverse=True))
    claims = []
    for match in re.finditer(MONEY.format(codes=codes), answer or "", re.I):
        try:
            claims.append(Decimal(match.group(1).replace(",", "").replace(" ", "")))
        except InvalidOperation:
            continue
    return claims


def unsupported(answer, results, currency="KES"):
    """The money amounts in ``answer`` that no tool result supports, as Decimals (empty when every one is supported)."""
    claims = money_claims(answer, currency)
    if not claims:
        return []
    numbers = sorted({abs(n) for n in numbers_in(results)})
    # Compared to the shilling (an answer rounds), so each figure and each sum or difference is kept as whole shillings.
    shillings = {int(n.to_integral_value()) for n in numbers}
    if len(numbers) <= MAX_PAIRS:
        for i, a in enumerate(numbers):
            for b in numbers[i:]:
                shillings.add(int((a + b).to_integral_value()))
                shillings.add(int(abs(a - b).to_integral_value()))

    def backed(value):
        whole = int(abs(value).to_integral_value())
        return whole == 0 or any(whole + step in shillings for step in (-1, 0, 1))

    return [claim for claim in claims if not backed(claim)]
