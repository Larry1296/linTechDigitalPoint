"""Database-level guards for new tenant tables, used from migrations.

Every tenant table gets the ``tenant_relationships`` trigger (defined in tenancy 0004), which rejects
a row whose foreign keys point at another business's records, even if application code is bypassed.
"""


def install_relationship_guards(apps, schema_editor, models):
    for app_label, name in models:
        model = apps.get_model(app_label, name)
        args = []
        for field in model._meta.concrete_fields:
            if field.is_relation and field.name != "organization":
                args.extend([field.column, field.remote_field.model._meta.db_table])
        table = schema_editor.quote_name(model._meta.db_table)
        arguments = ", ".join("'" + a + "'" for a in args)
        schema_editor.execute(f"DROP TRIGGER IF EXISTS tenant_relationships ON {table}")
        schema_editor.execute(f"CREATE TRIGGER tenant_relationships BEFORE INSERT OR UPDATE ON {table} "
                              f"FOR EACH ROW EXECUTE FUNCTION tenancy_check_relationships({arguments})")


def guard_migration(models):
    """A RunPython operation installing guards for (app_label, ModelName) pairs."""
    from django.db import migrations
    return migrations.RunPython(lambda apps, schema_editor: install_relationship_guards(apps, schema_editor, models),
                                migrations.RunPython.noop)
