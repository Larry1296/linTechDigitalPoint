from django.contrib.auth.models import Group, Permission
from apps.core.models import Store

ROLES = ["Manager", "Cashier", "Stock Controller", "Cyber Operator", "M-Pesa Operator", "Ecommerce Customer"]
ROLE_RULES = {
    "Manager": {"catalog", "inventory", "commerce", "accounts", "cyber", "mpesa"},
    "Cashier": {
        "commerce.add_sale",
        "commerce.view_sale",
        "commerce.add_payment",
        "commerce.view_payment",
        "catalog.view_product",
        "catalog.view_productvariant",
        "accounts.view_customerprofile",
    },
    "Stock Controller": {
        "catalog.view_category",
        "catalog.view_brand",
        "catalog.view_product",
        "catalog.view_productvariant",
        "catalog.add_product",
        "catalog.change_product",
        "catalog.add_productvariant",
        "catalog.change_productvariant",
        "inventory",
    },
    "Cyber Operator": {
        "cyber.view_cyberserviceprofile",
        "cyber.view_cyberjob",
        "cyber.add_cyberjob",
        "cyber.change_cyberjob",
        "cyber.view_cyberjobline",
        "cyber.add_cyberjobline",
        "cyber.complete_cyber_job",
        "commerce.add_sale",
        "commerce.add_payment",
        "commerce.view_sale",
    },
    "M-Pesa Operator": {
        "mpesa.view_mpesaoutlet",
        "mpesa.view_mpesasession",
        "mpesa.add_mpesasession",
        "mpesa.change_mpesasession",
        "mpesa.view_mpesatransaction",
        "mpesa.add_mpesatransaction",
        "mpesa.view_mpesareconciliation",
        "mpesa.add_mpesareconciliation",
    },
    "Ecommerce Customer": set(),
}


def ensure_initial_setup():
    store, _ = Store.objects.get_or_create(
        name="LinTech Digital Point", defaults={"currency": "KES", "timezone": "Africa/Nairobi"}
    )
    groups = {name: Group.objects.get_or_create(name=name)[0] for name in ROLES}
    all_permissions = Permission.objects.select_related("content_type").all()
    for role, rules in ROLE_RULES.items():
        selected = []
        for perm in all_permissions:
            app = perm.content_type.app_label
            key = f"{app}.{perm.codename}"
            if app in rules or key in rules:
                selected.append(perm)
        groups[role].permissions.set(selected)
    return store, groups
