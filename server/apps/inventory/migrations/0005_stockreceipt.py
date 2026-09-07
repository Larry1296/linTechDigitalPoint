from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_alter_movement_movement_type")]
    operations = [
        migrations.CreateModel(
            name="StockReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("COMPLETED", "Completed")], default="COMPLETED", max_length=20)),
                ("receipt_number", models.CharField(max_length=80, unique=True)), ("external_reference", models.CharField(blank=True, max_length=120)),
                ("supplier_name", models.CharField(blank=True, max_length=180)), ("received_at", models.DateTimeField()), ("notes", models.TextField(blank=True)),
                ("idempotency_key", models.CharField(blank=True, max_length=120, null=True, unique=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="stock_receipts", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="StockReceiptLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("received_quantity", models.DecimalField(decimal_places=3, max_digits=14)), ("unit_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("previous_selling_price", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)), ("new_selling_price", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("lot", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="receipt_line", to="inventory.stocklot")),
                ("receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="inventory.stockreceipt")),
                ("variant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipt_lines", to="catalog.productvariant")),
            ],
        ),
        migrations.CreateModel(
            name="StockReceiptPlacement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=14)),
                ("balance", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="receipt_placements", to="inventory.stockbalance")),
                ("line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="placements", to="inventory.stockreceiptline")),
                ("shelf", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipt_placements", to="inventory.shelf")),
            ],
        ),
        migrations.AddConstraint(model_name="stockreceiptline", constraint=models.CheckConstraint(condition=Q(("received_quantity__gt", 0), ("unit_cost__gte", 0)), name="positive_receipt_line")),
        migrations.AddConstraint(model_name="stockreceiptplacement", constraint=models.CheckConstraint(condition=Q(("quantity__gt", 0)), name="positive_receipt_placement")),
        migrations.AddConstraint(model_name="stockreceiptplacement", constraint=models.UniqueConstraint(fields=("line", "shelf"), name="unique_receipt_line_shelf")),
    ]
