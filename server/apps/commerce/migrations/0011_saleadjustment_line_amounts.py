from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('commerce', '0010_payment_reversed_status')]

    operations = [
        migrations.AddField(
            model_name='saleadjustment', name='line_amounts',
            field=models.JSONField(default=dict, blank=True),
        ),
    ]
