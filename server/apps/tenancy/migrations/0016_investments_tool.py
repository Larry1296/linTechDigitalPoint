"""Investments become a tool of their own, chosen at setup like M-Pesa agency and chama management.

They were part of the accounting pages, so every business on Pro saw them. The tool joins the Pro plan; a business keeps
it switched on only if it has already recorded an investment, and any other business can turn it on in Settings.
"""
from django.db import migrations

OLD_DESCRIPTION = "Everything in Basic plus reports, shelves & locations, staff accounts, branches and chama management."
DESCRIPTION = "Everything in Basic plus reports, shelves & locations, staff accounts, branches, chama management and investments."


def add(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    Organization = apps.get_model("tenancy", "Organization")
    Investment = apps.get_model("accounting", "Investment")
    for plan in Plan.objects.filter(code="PRO"):
        plan.enabled_modules = sorted(set(plan.enabled_modules) | {"investments"})
        if plan.description == OLD_DESCRIPTION:
            plan.description = DESCRIPTION
        plan.save(update_fields=["enabled_modules", "description"])
    investing = set(Investment.objects.values_list("organization_id", flat=True))
    for organization in Organization.objects.filter(pk__in=investing):
        if "investments" not in organization.enabled_modules:
            organization.enabled_modules = sorted([*organization.enabled_modules, "investments"])
            organization.save(update_fields=["enabled_modules"])


def remove(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    Organization = apps.get_model("tenancy", "Organization")
    for plan in Plan.objects.filter(code="PRO"):
        plan.enabled_modules = [module for module in plan.enabled_modules if module != "investments"]
        if plan.description == DESCRIPTION:
            plan.description = OLD_DESCRIPTION
        plan.save(update_fields=["enabled_modules", "description"])
    for organization in Organization.objects.filter(enabled_modules__contains=["investments"]):
        organization.enabled_modules = [module for module in organization.enabled_modules if module != "investments"]
        organization.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0015_business_kind"), ("accounting", "0013_alter_cashentry_kind_investment_investmentmovement_and_more")]
    operations = [migrations.RunPython(add, remove)]
