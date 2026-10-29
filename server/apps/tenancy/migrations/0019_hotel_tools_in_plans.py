"""The hotel tools, Menu & kitchen and Rooms & guests, are in every plan: they are what an eatery or a hotel runs on,
as products & stock are for a shop. Businesses choose to turn them on; they are never switched on for them."""
from django.db import migrations

HOTEL = {"menu", "rooms"}


def add(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    for plan in Plan.objects.all():
        plan.enabled_modules = sorted(set(plan.enabled_modules) | HOTEL)
        plan.save(update_fields=["enabled_modules"])


def remove(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    for plan in Plan.objects.all():
        plan.enabled_modules = [module for module in plan.enabled_modules if module not in HOTEL]
        plan.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0018_plan_prices")]
    operations = [migrations.RunPython(add, remove)]
