from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.tenancy.models import Organization
from apps.tenancy.context import organization_id
from apps.inventory.models import StockBalance, StockLot, Movement
from apps.accounting.ledger import money, reverse_journal
from apps.accounting.models import JournalEntry, CashEntry
from apps.accounting.services import reverse
from .models import Sale, Payment
from .returns import sale_balance, return_unit_cost

METHOD_WORDS = {'CASH': 'cash', 'MPESA': 'M-Pesa', 'BANK': 'bank', 'OTHER': 'other'}


def mpesa_code(method, reference):
    """An M-Pesa payment recorded with the code from its confirmation SMS is confirmed: the code is the proof the money
    arrived. Returns the code to confirm it with, or None when the payment must wait (no code, or not M-Pesa)."""
    code = ' '.join(str(reference or '').split()).upper()
    if method != 'MPESA' or not code:
        return None
    if Payment.objects.filter(provider_transaction_id=code).exists():
        raise ValidationError(f'The M-Pesa code {code} is already recorded on another payment. Check the code in the SMS.')
    return code


@transaction.atomic
def collect(*, sale, amount, method, key, reference='', confirmed=False):
    Organization.objects.select_for_update().get(pk=organization_id())
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    amount = money(amount)
    if sale.status != 'COMPLETED' or amount <= 0:
        raise ValidationError('Choose a completed sale and a positive payment.')
    if method not in {'CASH', 'BANK', 'MPESA', 'OTHER'}:
        raise ValidationError('Choose a valid payment method.')
    previous = Payment.objects.filter(idempotency_key=key).first()
    if previous:
        if (previous.sale_id, previous.amount, previous.method, previous.reference) != (sale.pk, amount, method, reference):
            raise ValidationError('Payment key already used for different details.')
        return previous
    # The M-Pesa code entered here for a sale whose M-Pesa payment is waiting is that payment's confirmation,
    # not a second payment.
    waiting = sale.payments.filter(method='MPESA', status__in=['PENDING', 'MANUAL_REVIEW'], amount=amount).order_by('pk').first()
    if method == 'MPESA' and reference.strip() and waiting:
        return confirm_payment(payment=waiting, reference=' '.join(reference.split()).upper())
    # Owed after returns and price corrections, not the original total.
    if amount > sale_balance(sale):
        raise ValidationError('Payment exceeds the outstanding balance.')
    if method == 'MPESA' and confirmed and not reference.strip():
        raise ValidationError('A confirmed mobile-money payment needs its provider reference.')
    code = mpesa_code(method, reference)
    return Payment.objects.create(sale=sale, method=method, amount=amount, idempotency_key=key,
        reference=reference, provider_transaction_id=code,
        status='COMPLETED' if method != 'MPESA' or code else 'MANUAL_REVIEW')


@transaction.atomic
def confirm_payment(*, payment, reference):
    Organization.objects.select_for_update().get(pk=organization_id())
    payment = Payment.objects.select_for_update(of=("self",)).get(pk=payment.pk)
    sale = Sale.objects.select_for_update().get(pk=payment.sale_id)
    if payment.status == 'COMPLETED':
        if payment.provider_transaction_id != reference:
            raise ValidationError('Payment was confirmed with a different reference.')
        return payment
    if payment.status not in {'PENDING', 'MANUAL_REVIEW'} or sale.status != 'COMPLETED':
        raise ValidationError('This payment cannot be confirmed.')
    if not reference.strip():
        raise ValidationError('Enter the provider confirmation reference.')
    owed = sale_balance(sale)
    if payment.amount > owed:
        # Usually the same money was also recorded another way (often as cash) while this one waited.
        others = ', '.join(f'{METHOD_WORDS.get(p.method, p.method.title())} {p.amount}' for p in sale.payments.filter(status='COMPLETED').exclude(pk=payment.pk))
        raise ValidationError(
            f'This sale already has {others or "other payments"} recorded, so only {max(owed, 0)} is still owed. '
            'If the customer paid once, by M-Pesa, reverse the other payment first and then confirm this one. '
            'If that other payment is the real one, mark this M-Pesa as not received.')
    if Payment.objects.filter(provider_transaction_id=reference).exclude(pk=payment.pk).exists():
        raise ValidationError('This provider reference is already recorded.')
    payment.status = 'COMPLETED'
    payment.provider_transaction_id = reference
    payment.updated_at = timezone.now()
    payment.save()
    return payment


@transaction.atomic
def dismiss_payment(*, payment, user, reason):
    """A waiting mobile-money payment that never arrived, or was the same money recorded twice: it is dropped,
    never counted. Nothing was posted for it, so there is nothing to reverse."""
    from apps.core.models import AuditLog
    Organization.objects.select_for_update().get(pk=organization_id())
    payment = Payment.objects.select_for_update(of=("self",)).get(pk=payment.pk)
    if not reason.strip():
        raise ValidationError('Say why this payment was not received.')
    if payment.status == 'FAILED':
        return payment
    if payment.status not in {'PENDING', 'MANUAL_REVIEW'}:
        raise ValidationError('Only a payment waiting for confirmation can be marked as not received.')
    payment.status = 'FAILED'
    payment.updated_at = timezone.now()
    payment.save(update_fields=['status', 'updated_at'])
    AuditLog.objects.create(action='PAYMENT_NOT_RECEIVED', object_type='Payment', object_id=str(payment.pk), user=user,
                            after={'sale': payment.sale_id, 'amount': str(payment.amount), 'method': payment.method, 'reason': reason})
    return payment


@transaction.atomic
def return_sale(*, sale, user, reason):
    Organization.objects.select_for_update().get(pk=organization_id())
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if not reason.strip():
        raise ValidationError('Explain why the sale is being returned.')
    if sale.status == 'REFUNDED':
        return sale
    if sale.status != 'COMPLETED' or sale.items.filter(variant__product__product_type='SERVICE').exists():
        raise ValidationError('Full stock returns are supported for completed goods sales.')
    if sale.returns.exists() or sale.adjustments.exists():
        raise ValidationError('This sale already has a partial return or price correction. Return the remaining items line by line instead.')
    original = JournalEntry.objects.filter(source_key=f'sale:{sale.pk}').first()
    if not original:
        raise ValidationError('Historical sales require an accountant-reviewed opening correction.')
    added_cost = Decimal(0)
    for item in sale.items.all():
        for allocation in item.allocations.select_related('lot', 'shelf'):
            added_cost += allocation.quantity * (return_unit_cost(allocation) - allocation.unit_cost)
            balance = StockBalance.objects.select_for_update().get(lot=allocation.lot, shelf=allocation.shelf)
            balance.quantity += allocation.quantity
            balance.save(update_fields=['quantity', 'updated_at'])
            StockLot.objects.filter(pk=allocation.lot_id).update(remaining_quantity=F('remaining_quantity')+allocation.quantity)
            Movement.objects.create(variant=item.variant, lot=allocation.lot, destination=allocation.shelf,
                quantity=allocation.quantity, movement_type='SALE_RETURN', reference=sale.number, performed_by=user)
    reverse_journal(original, user=user, reason=reason, key=f'return:{sale.pk}')
    if money(added_cost):
        from apps.accounting.ledger import post_journal, paired
        post_journal(key=f'return-cost:{sale.pk}', description=f'Return supplied buying cost for {sale.number}',
                     branch=sale.branch_id, user=user, lines=paired('1200', '5000', added_cost))
    for payment in sale.payments.filter(status='COMPLETED'):
        journal = JournalEntry.objects.get(source_key=f'payment:{payment.pk}')
        # Not "refund:<id>": that namespace belongs to partial-return refunds, keyed by return id.
        reverse_journal(journal, user=user, reason=reason, key=f'payment-refund:{payment.pk}')
        entry = CashEntry.objects.filter(source_key=f'payment:{payment.pk}').first()
        if entry:
            reverse(entry=entry, user=user, reason=reason)
        payment.status='REFUNDED'; payment.save(update_fields=['status'])
    sale.payments.filter(status__in=['PENDING','MANUAL_REVIEW']).update(status='FAILED')
    sale.status='REFUNDED'; sale.save(update_fields=['status', 'updated_at'])
    return sale
