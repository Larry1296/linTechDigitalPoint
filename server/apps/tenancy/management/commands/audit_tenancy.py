"""Read-only deployment verification; intentionally inspect all tenants by SQL."""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from apps.tenancy.base import TenantModel


class Command(BaseCommand):
    help = "Verify ownership, tenant foreign keys and PostgreSQL relationship guards without changing records."

    @transaction.atomic
    def handle(self, *args, **options):
        failures = []
        models = [model for model in apps.get_models() if issubclass(model, TenantModel)]
        quote = connection.ops.quote_name
        # One consistent snapshot across all tables, including a busy database.
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            for model in models:
                table = quote(model._meta.db_table)
                cursor.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE organization_id IS NULL) FROM {table}")
                count, missing = cursor.fetchone()
                self.stdout.write(f"{model._meta.label}: {count} records, {missing} unassigned")
                if missing:
                    failures.append(f"{model._meta.label}: missing ownership")
                cursor.execute("SELECT 1 FROM pg_trigger WHERE tgrelid = %s::regclass AND tgname = 'tenant_relationships' AND tgenabled = 'O'", [model._meta.db_table])
                if not cursor.fetchone():
                    failures.append(f"{model._meta.label}: relationship guard missing or disabled")
                for field in model._meta.concrete_fields:
                    if not field.is_relation or not issubclass(field.remote_field.model, TenantModel):
                        continue
                    related = quote(field.remote_field.model._meta.db_table)
                    column = quote(field.column)
                    cursor.execute(f"SELECT COUNT(*) FROM {table} src JOIN {related} dst ON src.{column} = dst.id WHERE src.organization_id IS DISTINCT FROM dst.organization_id")
                    if cursor.fetchone()[0]:
                        failures.append(f"{model._meta.label}.{field.name}: cross-business relationship")
        if failures:
            raise CommandError("; ".join(failures))
        self.stdout.write(self.style.SUCCESS(f"Verified {len(models)} tenant-owned tables. No ownership gaps found."))
