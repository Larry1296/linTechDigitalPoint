"""Assign legacy ownership without changing primary keys or business values."""
from django.db import migrations

DOMAIN_APPS = ['core', 'accounts', 'catalog', 'inventory', 'commerce', 'cyber', 'mpesa', 'accounting']
TRIGGERS = [
    ("inventory_stockadjustment", "immutable_stock_adjustment"),
    ("inventory_movement", "immutable_adjustment_movement"),
    ("inventory_stockreceiptlinecorrection", "immutable_receipt_correction"),
    ("inventory_movement", "immutable_receipt_correction_movement"),
]

def backfill(apps, schema_editor):
    Organization = apps.get_model("tenancy", "Organization")
    Membership = apps.get_model("tenancy", "Membership")
    Subscription = apps.get_model("tenancy", "OrganizationSubscription")
    User = apps.get_model("auth", "User")
    owner = User.objects.filter(is_active=True, is_superuser=True).order_by("pk").first() or User.objects.filter(is_active=True, is_staff=True).order_by("pk").first()
    stores = apps.get_model("core", "Store").objects.order_by("pk")
    store = stores.first()
    organization = Organization.objects.create(
        name="linTech Digital Point", slug="lintech-digital-point", owner_id=owner.pk if owner else None,
        currency=store.currency if store else "KES", timezone=store.timezone if store else "Africa/Nairobi",
        phone=store.phone if store else "", email=store.email if store else "", address=store.address if store else "",
    )
    Subscription.objects.create(organization=organization, status="ACTIVE")
    # Preserve global permissions as tenant-local grants. Do not grant all users ownership.
    for user in User.objects.all().iterator():
        permissions = set()
        for group in user.groups.all():
            permissions.update(f"{p.content_type.app_label}.{p.codename}" for p in group.permissions.select_related("content_type"))
        permissions.update(f"{p.content_type.app_label}.{p.codename}" for p in user.user_permissions.select_related("content_type"))
        if user.pk:
            role = "OWNER" if owner and user.pk == owner.pk else "ADMIN" if user.is_superuser else "READ_ONLY"
            # CUSTOM preserves exact legacy grants without the READ_ONLY role's extra views.
            if role == "READ_ONLY": role = "CUSTOM"
            Membership.objects.create(user=user, organization=organization, role=role,
                status="ACTIVE" if user.is_active and (user.is_staff or user.is_superuser) else "SUSPENDED", permissions=sorted(permissions))
    quote = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        for table, trigger in TRIGGERS:
            cursor.execute(f"ALTER TABLE {quote(table)} DISABLE TRIGGER {quote(trigger)}")
        for model in apps.get_models():
            if model._meta.app_label not in DOMAIN_APPS:
                continue
            table = quote(model._meta.db_table)
            cursor.execute(f"UPDATE {table} SET organization_id = %s WHERE organization_id IS NULL", [organization.pk])
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE organization_id IS NULL")
            if cursor.fetchone()[0]:
                raise RuntimeError(f"Unassigned organization records in {table}")
        # Flush deferred FK checks before PostgreSQL permits restoring triggers.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for table, trigger in TRIGGERS:
            cursor.execute(f"ALTER TABLE {quote(table)} ENABLE TRIGGER {quote(trigger)}")

class Migration(migrations.Migration):
    atomic = True
    dependencies = [('auth', '0012_alter_user_first_name_max_length'), ('contenttypes', '0002_remove_content_type_name'), ('tenancy', '0001_initial'), ('core', '0003_alter_auditlog_options_alter_store_options_and_more'), ('accounts', '0002_alter_customeraddress_options_and_more'), ('catalog', '0007_alter_brand_options_alter_category_options_and_more'), ('inventory', '0011_alter_locationhistory_options_alter_movement_options_and_more'), ('commerce', '0005_alter_cart_options_alter_cartitem_options_and_more'), ('cyber', '0002_alter_cyberjob_options_alter_cyberjobline_options_and_more'), ('mpesa', '0002_alter_mpesacommissionentry_options_and_more'), ('accounting', '0002_alter_cashaccount_options_alter_cashentry_options_and_more')]
    # Ownership assignment is deliberately irreversible; reverse deployment from backup.
    operations = [migrations.RunPython(backfill)]
