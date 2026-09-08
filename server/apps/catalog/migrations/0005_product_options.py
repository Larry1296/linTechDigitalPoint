from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[("catalog","0004_flag_mpesa_services_for_review")]
    operations=[
        migrations.CreateModel(name="ProductOptionType",fields=[("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),("created_at",models.DateTimeField(auto_now_add=True)),("updated_at",models.DateTimeField(auto_now=True)),("name",models.CharField(max_length=80)),("product",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="option_types",to="catalog.product"))]),
        migrations.CreateModel(name="ProductOptionValue",fields=[("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),("created_at",models.DateTimeField(auto_now_add=True)),("updated_at",models.DateTimeField(auto_now=True)),("value",models.CharField(max_length=120)),("option_type",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="values",to="catalog.productoptiontype"))]),
        migrations.CreateModel(name="ProductVariantOptionValue",fields=[("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),("created_at",models.DateTimeField(auto_now_add=True)),("updated_at",models.DateTimeField(auto_now=True)),("value",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="variant_assignments",to="catalog.productoptionvalue")),("variant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="option_assignments",to="catalog.productvariant"))]),
        migrations.AddConstraint(model_name="productoptiontype",constraint=models.UniqueConstraint(fields=("product","name"),name="unique_product_option_type")),
        migrations.AddConstraint(model_name="productoptionvalue",constraint=models.UniqueConstraint(fields=("option_type","value"),name="unique_product_option_value")),
        migrations.AddConstraint(model_name="productvariantoptionvalue",constraint=models.UniqueConstraint(fields=("variant","value"),name="unique_variant_option_value")),
    ]
