"""Database guard on the money check table: a check can never point at another business's records."""
from django.db import migrations
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):
    dependencies = [("accounting", "0011_money_check")]
    operations = [guard_migration([("accounting", "MoneyCheck")])]
