"""Chama management is a Pro tool. Businesses choose to turn it on; it is never switched on for them.

It was briefly called "kyama" before release; any business, plan or staff permission using that name is renamed.
"""
from django.db import migrations

DESCRIPTION = "Everything in Basic plus reports, shelves & locations, staff accounts, branches and chama management."


def _renamed(modules):
    return sorted({"chama" if module == "kyama" else module for module in modules})


def add(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    Organization = apps.get_model("tenancy", "Organization")
    Membership = apps.get_model("tenancy", "Membership")
    for plan in Plan.objects.all():
        modules = _renamed(plan.enabled_modules) if "kyama" in plan.enabled_modules else list(plan.enabled_modules)
        if plan.code == "PRO":
            modules = sorted(set(modules) | {"chama"})
            if plan.description.startswith("Everything in Basic plus reports"):
                plan.description = DESCRIPTION
        plan.enabled_modules = modules
        plan.save(update_fields=["enabled_modules", "description"])
    for organization in Organization.objects.filter(enabled_modules__contains=["kyama"]):
        organization.enabled_modules = _renamed(organization.enabled_modules)
        organization.save(update_fields=["enabled_modules"])
    for membership in Membership.objects.exclude(permissions=[]):
        if any(str(p).startswith("kyama.") for p in membership.permissions):
            membership.permissions = ["chama." + p[6:] if str(p).startswith("kyama.") else p for p in membership.permissions]
            membership.save(update_fields=["permissions"])


def remove(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    for plan in Plan.objects.filter(code="PRO"):
        plan.enabled_modules = [module for module in plan.enabled_modules if module != "chama"]
        plan.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0012_remove_empty_legacy_placeholder")]
    operations = [migrations.RunPython(add, remove)]
