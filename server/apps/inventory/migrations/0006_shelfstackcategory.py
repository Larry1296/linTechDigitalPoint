from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q

class Migration(migrations.Migration):
    dependencies=[("inventory","0005_stockreceipt"),("catalog","0005_product_options")]
    operations=[migrations.CreateModel(name="ShelfStackCategory",fields=[
        ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
        ("created_at",models.DateTimeField(auto_now_add=True)),("updated_at",models.DateTimeField(auto_now=True)),
        ("is_primary",models.BooleanField(default=False)),
        ("category",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="rack_assignments",to="catalog.category")),
        ("stack",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="category_assignments",to="inventory.shelfstack")),
    ]),migrations.AddConstraint(model_name="shelfstackcategory",constraint=models.UniqueConstraint(fields=("stack","category"),name="unique_stack_category")),migrations.AddConstraint(model_name="shelfstackcategory",constraint=models.UniqueConstraint(condition=Q(("is_primary",True)),fields=("stack",),name="one_primary_stack_category"))]
