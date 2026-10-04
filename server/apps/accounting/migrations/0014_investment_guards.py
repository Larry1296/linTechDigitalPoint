"""Investments are covered by the tenant relationship guard like every other business record."""
from django.db import migrations
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):
    dependencies = [("accounting", "0013_alter_cashentry_kind_investment_investmentmovement_and_more"), ("mpesa", "0009_alter_mpesatransaction_transaction_type"), ("tenancy", "0012_remove_empty_legacy_placeholder")]
    operations = [guard_migration([("accounting", "Investment"), ("accounting", "InvestmentMovement")])]
