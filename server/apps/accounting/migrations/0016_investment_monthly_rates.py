"""The fund's quoted yearly rate, recorded each month, and the withholding tax taken from interest."""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from apps.tenancy.guards import guard_migration


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0015_investment_purchase'),
        ('tenancy', '0012_remove_empty_legacy_placeholder'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='investment',
            name='tax_rate',
            field=models.DecimalField(decimal_places=2, default=15, max_digits=5),
        ),
        migrations.CreateModel(
            name='InvestmentRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField()),
                ('annual_rate', models.DecimalField(decimal_places=3, max_digits=6)),
                ('statement_balance', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('recorded_on', models.DateField()),
                ('note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('investment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='rates', to='accounting.investment')),
                ('organization', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='tenancy.organization')),
            ],
            options={
                'ordering': ['-month', '-pk'],
                'base_manager_name': 'objects',
                'default_manager_name': 'objects',
                'constraints': [models.UniqueConstraint(fields=('organization', 'investment', 'month'), name='acco_investmentrate_month_org'), models.CheckConstraint(condition=models.Q(('annual_rate__gte', 0), ('annual_rate__lte', 100)), name='acco_investmentrate_sensible')],
            },
        ),
        guard_migration([("accounting", "InvestmentRate")]),
    ]
