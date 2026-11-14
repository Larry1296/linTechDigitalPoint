"""Businesses describe themselves in their own words, and the platform owner runs any number of plans.

- Organization.description: what the business does, in the owner's words (set-up and Settings).
- SubscriptionPlan.highlighted: the plan the pricing pages recommend; Pro to start with.
- A "Business" plan between Basic and Pro (Basic's tools plus reports, shelves & locations and staff accounts). It is
  created switched off and without a price: the platform owner sets what it costs before it is offered.
- Plans are ordered Basic, Business, Pro.
"""
from django.db import migrations, models

BUSINESS_EXTRA = ["locations", "reports", "staff"]


def tiers(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    basic, pro = Plan.objects.filter(code="BASIC").first(), Plan.objects.filter(code="PRO").first()
    if basic:
        Plan.objects.filter(pk=basic.pk).update(sort_order=1)
    if pro:
        Plan.objects.filter(pk=pro.pk).update(sort_order=3, highlighted=True)
    if basic and not Plan.objects.filter(code="BUSINESS").exists():
        Plan.objects.create(code="BUSINESS", name="Business", price=0, currency=basic.currency, period_days=basic.period_days, sort_order=2,
                            active=False, enabled_modules=sorted(set(basic.enabled_modules) | set(BUSINESS_EXTRA)),
                            description="Everything in Basic plus reports, shelves & locations and staff accounts.")


def untier(apps, schema_editor):
    Plan = apps.get_model("tenancy", "SubscriptionPlan")
    Subscription = apps.get_model("tenancy", "OrganizationSubscription")
    Payment = apps.get_model("tenancy", "SubscriptionPayment")
    plan = Plan.objects.filter(code="BUSINESS").first()
    if plan and not Subscription.objects.filter(plan=plan).exists() and not Payment.objects.filter(plan=plan).exists():
        plan.delete()
    Plan.objects.filter(code="PRO").update(sort_order=2)


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0022_mkopa_tool"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="subscriptionplan",
            name="highlighted",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(tiers, untier),
    ]
