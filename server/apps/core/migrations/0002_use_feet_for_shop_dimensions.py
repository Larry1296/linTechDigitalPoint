from django.db import migrations, models


def use_feet(apps, schema_editor):
    Store = apps.get_model("core", "Store")
    Store.objects.filter(measurement_unit="cm").update(measurement_unit="ft")


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="store",
            name="measurement_unit",
            field=models.CharField(default="ft", max_length=10),
        ),
        migrations.RunPython(use_feet, migrations.RunPython.noop),
    ]
