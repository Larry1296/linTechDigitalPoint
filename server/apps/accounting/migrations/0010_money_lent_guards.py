"""Database guard on the Money lent tables: a loan or repayment can never point at another business's records."""
from django.db import migrations
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):
    dependencies = [("accounting", "0009_money_lent")]
    operations = [guard_migration([("accounting", "Loan"), ("accounting", "LoanRepayment")])]
