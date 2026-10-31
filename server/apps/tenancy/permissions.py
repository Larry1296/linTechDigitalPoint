"""Business permissions never inherit Django's global staff or superuser privileges."""
from django.contrib.auth.models import Permission
from .context import organization_id
from .models import Membership

DOMAIN_APPS = {"core", "catalog", "inventory", "commerce", "cyber", "mpesa", "accounting", "accounts", "chama", "hotel"}


# Pages the owner can keep an employee out of: (label, module the page belongs to or None, which permissions it is).
# Keeping someone out of a page takes those permissions away, so the page leaves their menu and its records are refused.
PAGES = {
    "sales": ("Selling (till, sales and customers)", "pos", lambda app, code: app == "commerce"),
    "products": ("Products and stock", "inventory", lambda app, code: app in {"catalog", "inventory"}),
    "services": ("Services (cyber)", "services", lambda app, code: app == "cyber"),
    "rooms": ("Rooms and guests", "rooms", lambda app, code: app == "hotel"),
    "mpesa": ("M-Pesa agency", "mpesa", lambda app, code: app == "mpesa"),
    "expenses": ("Money spent", "expenses", lambda app, code: app == "accounting" and "expense" in code),
    "loans": ("Money lent", None, lambda app, code: app == "accounting" and "loan" in code),
    "money": ("Money check and cash book", None, lambda app, code: app == "accounting" and ("moneycheck" in code or "cashentry" in code or "dailyclosing" in code)),
    "profit": ("Profit, costs and reports", None, lambda app, code: (app, code) == ("accounting", "view_profit") or (app == "accounting" and "journal" in code)),
    # Only ever given to an employee the owner ticks it for; anyone else never has it (owner_only).
    "investments": ("Investments", "investments", lambda app, code: app == "accounting" and "investment" in code),
}


# An employee's account: only the pages the owner ticks (Membership.open_pages), each with what it needs to work.
# The owner's side of the business (money, profit and costs, money spent and lent, chama, subscription, business
# settings, commission, staff) is never an employee's, whatever is ticked. Investments only if the owner ticks them.
WORK_PAGES = ("sales", "products", "services", "rooms", "mpesa", "investments")
CUSTOMERS = {"accounts.view_customerprofile", "accounts.add_customerprofile", "accounts.change_customerprofile"}
WORK_NEEDS = {
    "sales": lambda app, code: f"{app}.{code}" in CUSTOMERS or app in {"catalog", "inventory"} and code.startswith("view_"),
    "services": lambda app, code: f"{app}.{code}" in CUSTOMERS,
    "rooms": lambda app, code: f"{app}.{code}" in CUSTOMERS,
}
# The agency's commission, its shift reconciliations (expected against counted), outlet set-up and opening the shift
# are the owner's: the owner opens the day's shift, the employee records on it and closes it.
OWNERS_AGENCY = ("mpesacommissionentry", "mpesareconciliation", "add_mpesaoutlet", "change_mpesaoutlet", "delete_mpesaoutlet", "add_mpesasession")


def employee_permission(key, pages):
    app, _, code = key.partition(".")
    if key == "mpesa.add_mpesareconciliation":
        return "mpesa" in pages  # closing their own shift: they count, the owner sees what was expected
    # Deleting records (sales, products, outlets, ...) is the owner's: an employee cancels or corrects through the page.
    if app == "accounting" and "investment" in code:
        return "investments" in pages
    if app in {"accounting", "chama"} or code.startswith("delete_") or app == "mpesa" and any(part in code for part in OWNERS_AGENCY):
        return False
    return any(PAGES[page][2](app, code) or page in WORK_NEEDS and WORK_NEEDS[page](app, code) for page in pages if page in WORK_PAGES)


def is_employee(user):
    membership = membership_for(user)
    return bool(membership and membership.role == "EMPLOYEE")


def hidden(key, pages):
    app, _, code = key.partition(".")
    return any(page in PAGES and PAGES[page][2](app, code) for page in pages)


def owner_only(key):
    """Investments are the business owner's alone: never granted to anyone else, whatever their role or permissions."""
    app, _, code = key.partition(".")
    return app == "accounting" and "investment" in code

def membership_for(user):
    if not user or not user.is_authenticated or not user.is_active:
        return None
    return Membership.objects.filter(user_id=user.pk, organization_id=organization_id(), status="ACTIVE", organization__active=True).first()

def _business_permissions(user):
    membership = membership_for(user)
    if not membership:
        return set()
    available = {f"{app}.{code}" for app, code in Permission.objects.filter(content_type__app_label__in=DOMAIN_APPS).values_list("content_type__app_label", "codename")}
    if membership.role == "OWNER":
        return available
    if membership.role == "EMPLOYEE":
        return {key for key in available if employee_permission(key, membership.open_pages or [])}
    keep_out = membership.hidden_pages or []
    available = {key for key in available if not owner_only(key) and not hidden(key, keep_out)}
    if membership.role == "ADMIN":
        return available
    result = set(membership.permissions) & available
    for key in available:
        app, code = key.split(".")
        if app == "chama":
            continue  # the chama's members, ID numbers and money are not the shop's: never granted with a role
        if membership.role == "READ_ONLY" and code.startswith("view_") and code != "view_profit":
            result.add(key)
        elif membership.role == "MANAGER" and app in DOMAIN_APPS - {"accounts"}:
            result.add(key)
        elif membership.role == "INVENTORY" and app in {"inventory", "catalog"}:
            result.add(key)
        elif membership.role == "ACCOUNTANT" and app == "accounting":
            result.add(key)
        elif membership.role == "CASHIER" and key in {"commerce.add_sale", "commerce.view_sale", "commerce.add_payment", "commerce.view_payment", "accounts.view_customerprofile", "accounts.add_customerprofile", "catalog.view_product", "catalog.view_productvariant", "hotel.view_stay"}:
            result.add(key)
        elif membership.role == "SERVICE_ATTENDANT" and (app == "hotel" and code.endswith(("_stay", "_staydeposit", "_room")) or key in {"cyber.view_cyberserviceprofile", "cyber.view_cyberjob", "cyber.add_cyberjob", "cyber.change_cyberjob", "cyber.complete_cyber_job"}):
            result.add(key)
    return result

def has_business_permission(user, permission):
    return permission in business_permissions(user)

def is_business_owner(user):
    membership = membership_for(user)
    return bool(membership and membership.role == "OWNER")

def is_business_manager(user):
    membership = membership_for(user)
    return bool(membership and membership.role in {"OWNER", "ADMIN", "MANAGER"})

def business_permissions(user):
    cache = getattr(user, "_tenant_permission_cache", None)
    key = organization_id()
    if cache is None:
        return _business_permissions(user)
    if key not in cache:
        cache[key] = _business_permissions(user)
    return cache[key]
