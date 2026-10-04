"""Only unambiguous single-branch history is assigned automatically."""
from django.db import migrations

MODELS = [('commerce', 'Sale'), ('commerce', 'Order'), ('inventory', 'StockReceipt'),
          ('inventory', 'Reservation'), ('cyber', 'CyberJob'), ('accounting', 'CashEntry')]


def backfill(apps, schema_editor):
    Store = apps.get_model('core', 'Store')
    for org in apps.get_model('tenancy', 'Organization').objects.iterator():
        stores = list(Store.objects.filter(organization_id=org.pk).values_list('pk', flat=True)[:2])
        if len(stores) == 1:
            for app, name in MODELS:
                apps.get_model(app, name).objects.filter(organization_id=org.pk, branch_id=None).update(branch_id=stores[0])
    # Extend the existing organization relationship guards to cover new branch FKs.
    for app, name in MODELS:
        model = apps.get_model(app, name)
        args = []
        for field in model._meta.concrete_fields:
            if field.is_relation and field.name != 'organization':
                related = field.remote_field.model
                args.extend([field.column, related._meta.db_table])
        table = schema_editor.quote_name(model._meta.db_table)
        schema_editor.execute(f'DROP TRIGGER tenant_relationships ON {table}')
        arguments = ', '.join("'" + a + "'" for a in args)
        schema_editor.execute(f'CREATE TRIGGER tenant_relationships BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION tenancy_check_relationships({arguments})')


class Migration(migrations.Migration):
    dependencies = [('tenancy', '0005_branch_membership'), ('commerce', '0007_order_branch_sale_branch'),
        ('inventory', '0013_reservation_branch_stockreceipt_branch'), ('cyber', '0004_cyberjob_branch'),
        ('accounting', '0005_journal_integrity')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
