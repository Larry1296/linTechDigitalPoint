from django.db import migrations


def remove_empty_placeholder(apps, schema_editor):
    """0002 creates "linTech Digital Point" to hold pre-SaaS records. On a fresh install there are none, which leaves an
    ownerless business nobody can open; it would show on the platform's subscription list. Remove it only when empty."""
    Organization = apps.get_model("tenancy", "Organization")
    Store = apps.get_model("core", "Store")
    Membership = apps.get_model("tenancy", "Membership")
    Subscription = apps.get_model("tenancy", "OrganizationSubscription")
    for organization in Organization.objects.filter(slug="lintech-digital-point", owner__isnull=True):
        if Membership.objects.filter(organization=organization).exists() or Store.objects.filter(organization_id=organization.pk).exists():
            continue
        Subscription.objects.filter(organization=organization).delete()
        organization.delete()


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0011_subscription_billing"), ("core", "0004_alter_auditlog_organization_alter_store_organization")]
    operations = [migrations.RunPython(remove_empty_placeholder, migrations.RunPython.noop)]
