"""A daily chama rests on Sunday (services.py): contributions owed on a Sunday that nobody has paid or been fined for are
dropped, and a deadline that falls on a Sunday moves to Monday. A Sunday contribution that already has money on it is
kept as it is, so no payment is lost."""
from datetime import timedelta

from django.db import migrations

SUNDAY = 6


def rest_on_sunday(apps, schema_editor):
    Chama = apps.get_model("chama", "Chama")
    ChamaDue = apps.get_model("chama", "ChamaDue")
    ChamaAllocation = apps.get_model("chama", "ChamaAllocation")
    daily = list(Chama.objects.filter(frequency="DAILY").values_list("pk", flat=True))
    for due in ChamaDue.objects.filter(chama_id__in=daily):
        paid = ChamaAllocation.objects.filter(due_id=due.pk).exists()
        if due.period_date.weekday() == SUNDAY and not paid and not due.fine_amount:
            due.delete()
        elif due.deadline.weekday() == SUNDAY and not due.fine_checked:
            ChamaDue.objects.filter(pk=due.pk).update(deadline=due.deadline + timedelta(days=1))


class Migration(migrations.Migration):
    dependencies = [("chama", "0002_tenant_guards")]
    operations = [migrations.RunPython(rest_on_sunday, migrations.RunPython.noop)]
