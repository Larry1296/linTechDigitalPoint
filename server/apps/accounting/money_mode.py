"""How the owner keeps the money of the parts of the business (shop, cyber, M-Pesa agency), chosen when the business
is set up and changeable in Settings.

- ONE_DRAWER: all the cash sits in one drawer. Every amount is still labelled with the part that brought it in, so the
  dashboard and the money check show what each part produced.
- SEPARATE_CASH: each part keeps its own cash drawer, counted on its own; the Lipa na M-Pesa till and the bank stay
  shared, with each part's share shown.

Either way the M-Pesa agency's cash and float are the agency's money in operation, never the owner's; only the
commission it earns is the owner's, and it counts as the M-Pesa part's contribution.
"""
ONE_DRAWER, SEPARATE_CASH = "ONE_DRAWER", "SEPARATE_CASH"
MODES = {ONE_DRAWER: "One drawer for everything, each part's money labelled",
         SEPARATE_CASH: "A separate cash drawer for each part of the business"}
# The parts of the business, in order, with the tool that turns each on and how its money is named.
PARTS = [("SHOP", "pos", "Shop", "Shop sales"), ("CYBER", "services", "Cyber", "Cyber and services"),
         ("MPESA", "mpesa", "M-Pesa", "M-Pesa commission")]
NAMES = {key: name for key, _, name, _ in PARTS}
MONEY_NAMES = {key: money for key, _, _, money in PARTS}


def _organization(organization=None):
    if organization is not None:
        return organization
    from apps.tenancy.context import organization_id
    from apps.tenancy.models import Organization
    pk = organization_id()
    return Organization.objects.filter(pk=pk).first() if pk else None


def money_mode(organization=None):
    organization = _organization(organization)
    mode = ((organization.settings or {}) if organization else {}).get("money_mode")
    return mode if mode in MODES else ONE_DRAWER


def business_parts(organization=None):
    """The parts this business runs, from the tools it chose: ["SHOP", "CYBER", "MPESA"] or fewer."""
    organization = _organization(organization)
    if not organization:
        return ["SHOP"]
    from apps.tenancy.middleware import effective_modules
    enabled = effective_modules(organization)
    parts = [key for key, module, _, _ in PARTS if module in enabled]
    return parts or ["SHOP"]


def separate_cash(organization=None):
    """Separate drawers only mean something with more than one part that takes cash."""
    return money_mode(organization) == SEPARATE_CASH and len(business_parts(organization)) > 1
