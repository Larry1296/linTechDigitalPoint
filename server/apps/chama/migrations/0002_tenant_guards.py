"""Chama records may only point at records of the same business, enforced in the database too."""
from django.db import migrations
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):
    dependencies = [("chama", "0001_initial"), ("tenancy", "0004_relationship_guards")]
    operations = [guard_migration([("chama", name) for name in ["Chama", "ChamaMember", "ChamaDue", "ChamaPayment", "ChamaAllocation", "ChamaPayout"]])]
