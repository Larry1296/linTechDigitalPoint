"""A withdrawal from an investment can name the stock purchase it paid for; the tenant guard covers the new link."""
import django.db.models.deletion
from django.db import migrations, models
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):
    dependencies = [("accounting", "0014_investment_guards")]
    operations = [
        migrations.AddField(
            model_name="investmentmovement",
            name="purchase",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="investment_withdrawals", to="accounting.supplierpurchase"),
        ),
        guard_migration([("accounting", "InvestmentMovement")]),
    ]
