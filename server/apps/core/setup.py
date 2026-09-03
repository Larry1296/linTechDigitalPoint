from django.contrib.auth.models import Group,Permission
from apps.core.models import Store
from apps.inventory.models import Zone
ROLES=["Owner","Manager","Cashier","Stock Controller","Ecommerce Customer"]
ROLE_RULES={
"Manager":{"catalog","inventory","commerce","accounts"},
"Cashier":{"commerce.add_sale","commerce.view_sale","commerce.add_payment","commerce.view_payment","catalog.view_product","catalog.view_productvariant","accounts.view_customerprofile"},
"Stock Controller":{"catalog.view_category","catalog.view_brand","catalog.view_product","catalog.view_productvariant","catalog.add_product","catalog.change_product","catalog.add_productvariant","catalog.change_productvariant","inventory"},
"Ecommerce Customer":set(),
}
def ensure_initial_setup():
    store,_=Store.objects.get_or_create(name="LinTech Digital Point",defaults={"currency":"KES","timezone":"Africa/Nairobi"})
    for code,name in [("LEFT","Left Wall"),("BACK","Back Wall"),("RIGHT","Right Wall"),("COUNTER","Counter"),("OTHER","Other Storage")]: Zone.objects.get_or_create(store=store,code=code,defaults={"name":name})
    groups={name:Group.objects.get_or_create(name=name)[0] for name in ROLES}
    all_permissions=Permission.objects.select_related("content_type").all()
    groups["Owner"].permissions.set(all_permissions)
    for role,rules in ROLE_RULES.items():
        selected=[]
        for perm in all_permissions:
            app=perm.content_type.app_label; key=f"{app}.{perm.codename}"
            if app in rules or key in rules:selected.append(perm)
        groups[role].permissions.set(selected)
    return store,groups

