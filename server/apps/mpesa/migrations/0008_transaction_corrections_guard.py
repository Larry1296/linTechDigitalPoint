"""The new link from a correction to the entry it replaces is covered by the tenant relationship guard."""
from django.db import migrations
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):
    dependencies = [("mpesa", "0007_transaction_corrections")]
    operations = [guard_migration([("mpesa", "MpesaTransaction")])]
