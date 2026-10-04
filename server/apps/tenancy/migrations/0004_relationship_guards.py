from django.db import migrations

DOMAIN_APPS = ['core', 'accounts', 'catalog', 'inventory', 'commerce', 'cyber', 'mpesa', 'accounting']
FUNCTION = """
CREATE FUNCTION tenancy_check_relationships() RETURNS trigger AS $$
DECLARE
    related_organization bigint;
    related_id bigint;
    i integer;
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.organization_id IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'Organization ownership cannot change' USING ERRCODE = '23514';
    END IF;
    i := 0;
    WHILE i < TG_NARGS LOOP
        related_id := (to_jsonb(NEW) ->> TG_ARGV[i])::bigint;
        IF related_id IS NOT NULL THEN
            IF TG_ARGV[i+1] = 'auth_user' THEN
                SELECT organization_id INTO related_organization FROM tenancy_membership
                    WHERE organization_id = NEW.organization_id AND user_id = related_id;
                IF related_organization IS NULL THEN
                    SELECT organization_id INTO related_organization FROM accounts_customerprofile
                        WHERE organization_id = NEW.organization_id AND user_id = related_id;
                END IF;
            ELSE
                EXECUTE format('SELECT organization_id FROM %I WHERE id = $1', TG_ARGV[i+1])
                    INTO related_organization USING related_id;
            END IF;
            IF related_organization IS DISTINCT FROM NEW.organization_id THEN
                RAISE EXCEPTION 'Invalid business relationship' USING ERRCODE = '23514';
            END IF;
        END IF;
        i := i + 2;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

def install(apps, schema_editor):
    schema_editor.execute(FUNCTION, params=None)
    for model in apps.get_models():
        if model._meta.app_label not in DOMAIN_APPS: continue
        arguments = []
        for field in model._meta.concrete_fields:
            if field.is_relation and (field.remote_field.model._meta.app_label in DOMAIN_APPS or (field.remote_field.model._meta.label_lower == "auth.user" and model._meta.model_name != "customerprofile")):
                arguments.extend([field.column, field.remote_field.model._meta.db_table])
        args = ', '.join("'" + arg + "'" for arg in arguments)
        table = schema_editor.quote_name(model._meta.db_table)
        schema_editor.execute(f"CREATE TRIGGER tenant_relationships BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION tenancy_check_relationships({args})")

def uninstall(apps, schema_editor):
    for model in apps.get_models():
        if model._meta.app_label in DOMAIN_APPS:
            schema_editor.execute(f"DROP TRIGGER tenant_relationships ON {schema_editor.quote_name(model._meta.db_table)}")
    schema_editor.execute("DROP FUNCTION tenancy_check_relationships()")

class Migration(migrations.Migration):
    dependencies = [('tenancy', '0003_alter_membership_role'), ('core', '0004_alter_auditlog_organization_alter_store_organization'), ('accounts', '0003_alter_customeraddress_organization_and_more'), ('catalog', '0008_alter_brand_organization_alter_category_organization_and_more'), ('inventory', '0012_alter_locationhistory_organization_and_more'), ('commerce', '0006_alter_cart_organization_alter_cartitem_organization_and_more'), ('cyber', '0003_alter_cyberjob_organization_and_more'), ('mpesa', '0003_alter_mpesacommissionentry_organization_and_more'), ('accounting', '0003_alter_cashaccount_organization_and_more')]
    operations = [migrations.RunPython(install, uninstall)]
