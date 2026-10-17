"""Where customers' M-Pesa for sales lands, the agent line or a till of the business's own.

Each part of the business keeps its own money, even with one drawer: the M-Pesa agency's shift counts only the
agency's cash and float, and the shop's and cyber's money is theirs, on their own pages and in the money check.
"""
AGENT_LINE, TILL = "AGENT_LINE", "TILL"


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
