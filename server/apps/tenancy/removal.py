"""Permanently removing a business and everything it recorded, for the platform administrator.

The books are append-only on purpose: posted journals and stock adjustments have database triggers that refuse
deletes. Removing a whole business is the one deliberate exception, so those triggers are switched off only inside
the deleting transaction and only for its tables. Foreign keys stay checked (Django creates them deferred), so if
anything outside the business still points at its rows the whole removal is rolled back and nothing is lost.
User accounts are kept: people can belong to other businesses or shop as customers.
"""
import logging

from django.apps import apps
from django.db import connection, models, transaction

from .models import Organization

log = logging.getLogger(__name__)


def _business_tables():
    """(model, column) for every table whose rows belong to one business through a link to Organization."""
    found = []
    for model in apps.get_models(include_auto_created=True):
        if model is Organization or model._meta.proxy or not model._meta.managed:
            continue
        for field in model._meta.concrete_fields:
            if field.is_relation and field.remote_field.model is Organization:
                found.append((model, field.column))
                break
    return found


def _dependents(owned):
    """Links from tables outside the business to rows the business owns, e.g. branch staff or many-to-many rows."""
    owned_models = {model: column for model, column in owned}
    owned_models[Organization] = "id"
    links = []
    for model in apps.get_models(include_auto_created=True):
        if model in owned_models or model._meta.proxy or not model._meta.managed:
            continue
        for field in model._meta.concrete_fields:
            target = field.remote_field.model if field.is_relation else None
            if target in owned_models and isinstance(field, models.ForeignKey):
                links.append((model, field, target, owned_models[target]))
    return links


def _quote(name):
    return connection.ops.quote_name(name)


def _guarded(tables):
    with connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT tgrelid::regclass::text FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text = ANY(%s)",
                       [list(tables)])
        return [row[0] for row in cursor.fetchall()]


def delete_business(organization):
    """Delete the business and all its records. Returns how many rows were removed from each table."""
    org_id = organization.pk
    owned = _business_tables()
    files = []
    removed = {}
    with transaction.atomic(), connection.cursor() as cursor:
        # Postgres only lets a table's triggers change when no link checks are waiting, so settle those first.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        guarded = _guarded(model._meta.db_table for model, _ in owned)
        for table in guarded:
            cursor.execute(f"ALTER TABLE {_quote(table)} DISABLE TRIGGER USER")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        # Rows outside the business that point into it: clear optional links, remove the rest.
        for model, field, target, column in _dependents(owned):
            inside = f"SELECT id FROM {_quote(target._meta.db_table)} WHERE {_quote(column)} = %s"
            table, link = _quote(model._meta.db_table), _quote(field.column)
            if field.null:
                cursor.execute(f"UPDATE {table} SET {link} = NULL WHERE {link} IN ({inside})", [org_id])
            else:
                cursor.execute(f"DELETE FROM {table} WHERE {link} IN ({inside})", [org_id])
                removed[model._meta.label] = removed.get(model._meta.label, 0) + cursor.rowcount
        for model, column in [*owned, (Organization, "id")]:
            for field in model._meta.concrete_fields:
                if isinstance(field, models.FileField):
                    cursor.execute(f"SELECT {_quote(field.column)} FROM {_quote(model._meta.db_table)} WHERE {_quote(column)} = %s AND {_quote(field.column)} <> ''",
                                   [org_id])
                    files += [(field.storage, name) for (name,) in cursor.fetchall()]
        for model, column in owned:
            cursor.execute(f"DELETE FROM {_quote(model._meta.db_table)} WHERE {_quote(column)} = %s", [org_id])
            if cursor.rowcount:
                removed[model._meta.label] = removed.get(model._meta.label, 0) + cursor.rowcount
        cursor.execute(f"DELETE FROM {_quote(Organization._meta.db_table)} WHERE id = %s", [org_id])
        # Check every deferred link now, so a problem is reported here and rolls everything back.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for table in guarded:
            cursor.execute(f"ALTER TABLE {_quote(table)} ENABLE TRIGGER USER")

        def remove_files():
            for storage, name in files:
                try:
                    storage.delete(name)
                except Exception:  # a missing file must not undo the removal
                    log.warning("Could not delete %s while removing business %s", name, org_id)
        transaction.on_commit(remove_files)
    log.warning("Business %s (%s) was permanently deleted: %s", org_id, organization.name, removed)
    return removed
