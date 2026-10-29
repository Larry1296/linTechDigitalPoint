"""Business permissions never inherit Django's global staff or superuser privileges."""
from django.contrib.auth.models import Permission
from .context import organization_id
from .models import Membership

DOMAIN_APPS = {"core", "catalog", "inventory", "commerce", "cyber", "mpesa", "accounting", "accounts", "chama", "hotel"}

def membership_for(user):
    if not user or not user.is_authenticated or not user.is_active:
        return None
    return Membership.objects.filter(user_id=user.pk, organization_id=organization_id(), status="ACTIVE", organization__active=True).first()

def _business_permissions(user):
    membership = membership_for(user)
    if not membership:
        return set()
    available = {f"{app}.{code}" for app, code in Permission.objects.filter(content_type__app_label__in=DOMAIN_APPS).values_list("content_type__app_label", "codename")}
    if membership.role in {"OWNER", "ADMIN"}:
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
