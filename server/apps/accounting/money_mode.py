"""How the owner keeps the money of the parts of the business (shop, cyber, M-Pesa agency), chosen when the business
is set up and changeable in Settings.

- ONE_DRAWER: all the cash sits in one drawer. Every amount is still labelled with the part that brought it in, so the
  dashboard and the money check show what each part produced.
- SEPARATE_CASH: each part keeps its own cash drawer, counted on its own; the Lipa na M-Pesa till and the bank stay
  shared, with each part's share shown.

Either way the M-Pesa agency's cash and float are the agency's money in operation, never the owner's; only the
commission it earns is the owner's, and it counts as the M-Pesa part's contribution.

Whether the business is made of parts at all is the owner's answer too (``structure``): a salon that also sells hair
products is one business, while a cyber with a shop and an M-Pesa agency is several under one name. Only a business
with parts sees each part's contribution and shares its running costs between them. Profit is always the whole
business's: the parts' contributions add up to it. The owner may name each part ("Salon", "Spares").
"""
ONE_DRAWER, SEPARATE_CASH = "ONE_DRAWER", "SEPARATE_CASH"
MODES = {ONE_DRAWER: "One drawer for everything, each part's money labelled",
         SEPARATE_CASH: "A separate cash drawer for each part of the business"}
# The parts of the business, in order, with the tool that turns each on and how its money is named.
PARTS = [("SHOP", "inventory", "Shop", "Shop sales"), ("CYBER", "services", "Cyber", "Cyber and services"),
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


ONE_BUSINESS, WITH_PARTS = "SINGLE", "PARTS"
STRUCTURES = {ONE_BUSINESS: "One business", WITH_PARTS: "Several businesses under one name"}


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
    """Separate drawers only mean something for a business made of more than one part."""
    return money_mode(organization) == SEPARATE_CASH and has_parts(organization)


def structure(organization=None):
    """SINGLE or PARTS. Businesses that never answered keep what they had: parts when more than one part earns."""
    organization = _organization(organization)
    if not organization:
        return ONE_BUSINESS
    chosen = (organization.settings or {}).get("structure")
    if chosen in STRUCTURES:
        return chosen
    return WITH_PARTS if len(business_parts(organization)) > 1 else ONE_BUSINESS


def has_parts(organization=None):
    organization = _organization(organization)
    return structure(organization) == WITH_PARTS and len(business_parts(organization)) > 1


def default_name(key, sector=""):
    """A part's usual name. The services part is "Cyber" for a cyber (and for businesses set up before kinds existed)."""
    if key == "CYBER" and sector and "cyber" not in sector:
        return "Services"
    return NAMES[key]


def part_names(organization=None):
    """{key: name} for every part, with the owner's own names where given."""
    organization = _organization(organization)
    own = ((organization.settings or {}) if organization else {}).get("part_names") or {}
    sector = organization.sector if organization else ""
    return {key: (str(own.get(key) or "").strip() or default_name(key, sector)) for key, _, _, _ in PARTS}


def money_names(organization=None):
    """How each part's money is named on the money check and dashboard: "Shop sales", or the owner's part name."""
    organization = _organization(organization)
    own = ((organization.settings or {}) if organization else {}).get("part_names") or {}
    return {key: (str(own.get(key) or "").strip() or money) for key, _, _, money in PARTS}


def parts_data(organization=None):
    """The parts this business runs, named, for the browser."""
    names = part_names(organization)
    return [{"key": key, "name": names[key]} for key in business_parts(organization)]
