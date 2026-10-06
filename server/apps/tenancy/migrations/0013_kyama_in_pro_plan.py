"""Kyama (chama) management is a Pro tool. Businesses choose to turn it on; it is never switched on for them."""
from django.db import migrations

DESCRIPTION = "Everything in Basic plus reports, shelves & locations, staff accounts, branches and kyama (chama) management."


def add(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    for plan in Plan.objects.filter(code="PRO"):
        plan.enabled_modules = sorted(set(plan.enabled_modules) | {"kyama"})
        if plan.description.startswith("Everything in Basic plus reports"):
            plan.description = DESCRIPTION
        plan.save(update_fields=["enabled_modules", "description"])


def remove(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    for plan in Plan.objects.filter(code="PRO"):
        plan.enabled_modules = [module for module in plan.enabled_modules if module != "kyama"]
        plan.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0012_remove_empty_legacy_placeholder")]
    operations = [migrations.RunPython(add, remove)]
