"""Hotel records may only point at records of the same business, enforced in the database too."""
from django.db import migrations
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):
    dependencies = [("hotel", "0001_initial"), ("tenancy", "0004_relationship_guards")]
    operations = [guard_migration([("hotel", name) for name in ["MenuItem", "KitchenIngredient", "KitchenUse", "KitchenUseLine", "RoomType",
                                                                 "Room", "Stay", "StayCharge", "StayDeposit"]])]
