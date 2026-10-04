from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0004_relationship_guards"),
        ("core", "0004_alter_auditlog_organization_alter_store_organization"),
    ]

    operations = [
        migrations.CreateModel(
            name="BranchMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("ADMIN", "Branch Admin"), ("MANAGER", "Branch Manager"), ("STAFF", "Branch Staff")], default="STAFF", max_length=16)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("SUSPENDED", "Suspended")], default="ACTIVE", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="memberships", to="core.store")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="branch_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("user", "store"), name="unique_branch_membership")]},
        ),
    ]
