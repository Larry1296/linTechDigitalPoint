from django.db import migrations


def flag_mpesa_services(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    AuditLog = apps.get_model("core", "AuditLog")
    candidates = Product.objects.filter(product_type="SERVICE", name__icontains="m-pesa") | Product.objects.filter(
        product_type="SERVICE", name__icontains="mpesa"
    )
    for product in candidates.distinct():
        product.online_orderable = False
        product.save(update_fields=["online_orderable"])
        AuditLog.objects.create(
            action="MPESA_SERVICE_REVIEW_REQUIRED",
            object_type="Product",
            object_id=str(product.pk),
            before={"online_orderable": True},
            after={"online_orderable": False, "reason": "Potential legacy M-Pesa agency service; retained for owner review."},
        )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_product_online_orderable"), ("core", "0002_use_feet_for_shop_dimensions")]
    operations = [migrations.RunPython(flag_mpesa_services, migrations.RunPython.noop)]
