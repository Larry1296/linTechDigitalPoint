import re

from django.db import migrations, models

# Items already named as sold per measure, e.g. "2.5MM TWIN & EARTH CABLE (PER METRE)", start out sold by that measure.
MEASURES = [("METRE", r"\bPER\s*(METRE|METER|MTR|M)\b"), ("KG", r"\bPER\s*(KG|KILO|KILOGRAM)S?\b"), ("LITRE", r"\bPER\s*(LITRE|LITER|LTR|L)\b")]


def from_names(apps, schema_editor):
    Variant = apps.get_model("catalog", "ProductVariant")
    for variant in Variant._base_manager.select_related("product").all():
        text = f"{variant.product.name} {variant.name}"
        for measure, pattern in MEASURES:
            if re.search(pattern, text, re.IGNORECASE):
                Variant._base_manager.filter(pk=variant.pk).update(sold_by=measure)
                break


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0011_variant_sold_in_packs"),
    ]

    operations = [
        migrations.AddField(
            model_name="productvariant",
            name="sold_by",
            field=models.CharField(choices=[("PIECE", "Piece"), ("METRE", "Metre"), ("KG", "Kilogram"), ("LITRE", "Litre")], default="PIECE", max_length=8),
        ),
        migrations.RunPython(from_names, migrations.RunPython.noop),
    ]
