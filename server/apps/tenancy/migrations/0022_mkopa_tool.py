"""M-KOPA phones become a tool, chosen at setup like the M-Pesa agency. Every plan that has the agency gets it too;
no business has it switched on until its owner turns it on in Settings."""
from django.db import migrations


def add(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    for plan in Plan.objects.all():
        if "mpesa" in plan.enabled_modules and "mkopa" not in plan.enabled_modules:
            plan.enabled_modules = sorted([*plan.enabled_modules, "mkopa"])
            plan.save(update_fields=["enabled_modules"])


def remove(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    for plan in Plan.objects.all():
        if "mkopa" in plan.enabled_modules:
            plan.enabled_modules = [module for module in plan.enabled_modules if module != "mkopa"]
            plan.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0021_employees")]
    operations = [migrations.RunPython(add, remove)]
