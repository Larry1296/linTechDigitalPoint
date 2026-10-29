from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.commerce.models import Payment
from apps.mpesa.models import MpesaTransaction
from .services import post


@receiver(post_save, sender=Payment)
def payment_posted(sender, instance, **kwargs):
    if instance.status != 'COMPLETED' or not instance.sale_id:
        return
    from .ledger import post_collection
    post_collection(instance)
    sale = instance.sale
    if instance.method == 'DEPOSIT':
        return  # a guest's deposit counted as money in when it was paid; using it moves no money
    # The sale is finalized before its payment is posted by POS and Cyber services. The money counts on the
    # day it was confirmed (updated_at), the same day as its journal, not the day an M-Pesa prompt was sent.
    post(unit='CYBER' if sale.channel in ('CYBER', 'ROOMS') else 'SHOP', method=instance.method,
        amount=instance.amount, cogs=sale.cogs * instance.amount / sale.total if sale.total else 0,
        kind='INCOME', reference=sale.number, key=f'payment:{instance.pk}', user=sale.created_by, occurred_at=instance.updated_at, branch=sale.branch)


@receiver(post_save, sender=MpesaTransaction)
def principal_posted(sender, instance, **kwargs):
    from .ledger import post_journal, paired
    from django.utils import timezone
    lines = paired('1300', '3000', instance.cash_delta) + paired('1310', '3000', instance.float_delta)
    # Principal exchanges cancel through equity; external top-ups remain capital movements.
    if instance.cash_delta or instance.float_delta:
        post_journal(key=f'agency:{instance.pk}', description=instance.internal_reference,
            branch=instance.outlet.store_id, date=timezone.localtime(instance.occurred_at).date(),
            user=instance.performed_by, lines=lines)
    for method, amount in [('AGENCY_CASH', instance.cash_delta), ('AGENCY_FLOAT', instance.float_delta)]:
        post(unit='MPESA', method=method, amount=amount, kind='PRINCIPAL', reference=instance.internal_reference,
            key=f'mpesa:{instance.pk}:{method}', user=instance.performed_by, occurred_at=instance.occurred_at,
            branch=instance.outlet.store)
