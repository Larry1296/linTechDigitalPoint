"""Daily chamas contribute every day of the week, Sunday included (undoing 0003).

For each daily chama, every day from the start up to the day contributions are owed through gets its contribution again,
for every member who belonged that day. A Sunday put back is never fined. Deadlines go back to the day plus the grace
days. Where a Sunday was put back, the member's payments are shared out again oldest day first, as when they were
recorded, so money paid on a Sunday counts for that Sunday instead of the Monday after it."""
from datetime import timedelta
from decimal import Decimal

from django.db import migrations


def every_day_again(apps, schema_editor):
    Chama = apps.get_model("chama", "Chama")
    ChamaDue = apps.get_model("chama", "ChamaDue")
    ChamaAllocation = apps.get_model("chama", "ChamaAllocation")
    for chama in Chama.objects.filter(frequency="DAILY", dues_through__isnull=False):
        members = list(apps.get_model("chama", "ChamaMember").objects.filter(chama_id=chama.pk))
        existing = set(ChamaDue.objects.filter(chama_id=chama.pk).values_list("member_id", "period_date"))
        restored = set()
        day = chama.start_date
        while day <= chama.dues_through:
            for member in members:
                owed = member.joined_on <= day and (member.left_on is None or day < member.left_on)
                if owed and (member.pk, day) not in existing:
                    ChamaDue.objects.create(organization_id=chama.organization_id, chama_id=chama.pk, member_id=member.pk, period_date=day,
                                            amount=chama.contribution_amount, deadline=day + timedelta(days=chama.grace_days),
                                            fine_checked=True)
                    restored.add(member.pk)
            day += timedelta(days=1)
        for due in ChamaDue.objects.filter(chama_id=chama.pk, excused_until__isnull=True, fine_amount=0):
            right = due.period_date + timedelta(days=chama.grace_days)
            if due.deadline != right:
                ChamaDue.objects.filter(pk=due.pk).update(deadline=right)
        for member_id in restored:
            _share_out_again(ChamaDue, ChamaAllocation, member_id)


def _share_out_again(ChamaDue, ChamaAllocation, member_id):
    """The member's contribution money, payment by payment in the order paid, onto their oldest unpaid days."""
    allocations = (ChamaAllocation.objects.filter(due__member_id=member_id, part="CONTRIBUTION", payment__reversed_at__isnull=True)
                   .select_related("payment").order_by("payment__paid_on", "payment_id", "pk"))
    per_payment = {}
    for allocation in allocations:
        per_payment.setdefault(allocation.payment_id, [allocation.payment, Decimal("0")])[1] += allocation.amount
    allocations.delete()
    dues = list(ChamaDue.objects.filter(member_id=member_id).order_by("period_date", "pk"))
    room = {due.pk: due.amount for due in dues}
    for payment, amount in per_payment.values():
        for due in dues:
            if amount <= 0:
                break
            take = min(amount, room[due.pk])
            if take > 0:
                ChamaAllocation.objects.create(organization_id=payment.organization_id, payment_id=payment.pk, due_id=due.pk, part="CONTRIBUTION", amount=take)
                room[due.pk] -= take
                amount -= take


class Migration(migrations.Migration):
    dependencies = [("chama", "0003_daily_rest_on_sunday")]
    operations = [migrations.RunPython(every_day_again, migrations.RunPython.noop)]
