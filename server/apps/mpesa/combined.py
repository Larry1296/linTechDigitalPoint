"""One drawer and one agent line for the whole business: the M-Pesa shift counts all of it.

A business that keeps all its cash in one drawer (money_mode.ONE_DRAWER) and runs an M-Pesa agency next to its shop or
cyber has the agency's cash and the shop's takings in the same drawer, and, when customers pay for sales by sending
M-Pesa to the agent line, the agency's float and the sales money on the same line. Nobody can count them apart, so the
shift counts everything: all the cash in the drawer, all the money on the line.

The cash book already says how much of it is the business's own (``business_money``): every sale paid in cash or by
M-Pesa, less what was spent from the drawer, labelled with the part that brought it. The agency's part is the rest. So
a combined shift keeps the agency's figures as the agency's (deposits and withdrawals move them, as always) and the
business's as the business's, and at closing:

    expected in the drawer = the agency's cash (opening part + its deposits and withdrawals) + the business's cash now
    expected on the line   = the agency's float (opening part + its movements) + the business's M-Pesa sales money now

Whatever differs from the count is the shift's difference, explained by its reason. The agency's stored figures (and so
money in operation and net worth) never include the business's money: nothing is counted twice.
"""
from decimal import Decimal

from django.db.models import Sum

ZERO = Decimal("0")
AGENT_LINE, TILL = "AGENT_LINE", "TILL"
KIND_WORDS = {"INCOME": "received from customers", "EXPENSE": "spent on running costs", "PURCHASE": "paid to suppliers",
              "LOAN": "lent, less repaid", "INVESTMENT": "put into investments, less taken out", "OPENING": "starting money"}


def _organization(organization=None):
    from apps.accounting.money_mode import _organization as find
    return find(organization)


def sale_mpesa_to(organization=None):
    """Where customers' M-Pesa for sales lands: the agent line (AGENT_LINE) or a till of the business's own (TILL).
    The owner says so in Settings; until then, a business with a Safaricom till or paybill set up uses it, and one
    without uses the agent line."""
    from apps.tenancy.models import MpesaExpressSetup
    organization = _organization(organization)
    if not organization:
        return TILL
    chosen = (organization.settings or {}).get("sale_mpesa_to")
    if chosen in (AGENT_LINE, TILL):
        return chosen
    setup = MpesaExpressSetup.objects.filter(organization=organization).first()
    return TILL if setup and setup.kind != MpesaExpressSetup.NONE else AGENT_LINE


def combined(organization=None):
    """The shift counts the whole business's money: one drawer, and an agency next to another part of the business."""
    from apps.accounting.money_mode import ONE_DRAWER, business_parts, money_mode
    organization = _organization(organization)
    if not organization or money_mode(organization) != ONE_DRAWER:
        return False
    parts = business_parts(organization)
    return "MPESA" in parts and len(parts) > 1


def business_money(organization=None):
    """(cash, line): the business's own money in the drawer and on the agent line now, from the cash book."""
    from apps.accounting.money_check import expected
    cash = expected("CASH")[0]
    line = expected("MPESA")[0] if sale_mpesa_to(organization) == AGENT_LINE else ZERO
    return cash, line


def business_since(since, organization=None):
    """What the business's own money in the drawer and on the line did since ``since``, part by part:
    [{"label", "cash", "line"}], e.g. Shop received from customers +8,500 cash, +1,200 on the line."""
    from apps.accounting.models import CashEntry
    from apps.accounting.money_mode import part_names
    methods = ["CASH", "MPESA"] if sale_mpesa_to(organization) == AGENT_LINE else ["CASH"]
    rows = (CashEntry.objects.filter(account__payment_method__in=methods, occurred_at__gte=since)
            .values("business_unit", "kind", "account__payment_method").annotate(total=Sum("amount")))
    names = part_names(organization)
    lines = {}
    for row in rows:
        key = (row["business_unit"], row["kind"])
        line = lines.setdefault(key, {"label": f"{names.get(row['business_unit'], row['business_unit'])} {KIND_WORDS.get(row['kind'], row['kind'].lower())}",
                                      "cash": ZERO, "line": ZERO})
        line["cash" if row["account__payment_method"] == "CASH" else "line"] += row["total"] or ZERO
    return [line for line in lines.values() if line["cash"] or line["line"]]


def view(session=None, organization=None):
    """For the desk: whether the shift counts everything, where sale M-Pesa goes, the business's part now and, with a
    shift open, what the business's money did since it opened."""
    if not combined(organization):
        return None
    cash, line = business_money(organization)
    data = {"sale_mpesa_to": sale_mpesa_to(organization), "business_cash": cash, "business_line": line}
    if session is not None and session.business_cash_at_open is not None:
        data.update(business_cash_at_open=session.business_cash_at_open, business_line_at_open=session.business_line_at_open,
                    since_open=business_since(session.opened_at, organization))
    return data
