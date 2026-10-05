from decimal import Decimal
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.permissions import HasLinTechPermission
from apps.accounts.models import CustomerProfile
from .models import Sale, Payment
from .returns import sale_amounts, sale_balance
from .settlements import collect, confirm_payment, delete_payment, delete_sale, dismiss_payment, return_sale


class SalesView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'commerce.view_sale'
    def get(self, request):
        from django.db.models import Q
        page = serializers.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
        # A deleted sale (recorded by mistake) is out of the books and out of this list.
        rows = Sale.objects.exclude(status='CANCELLED').select_related('customer').prefetch_related('payments', 'items__variant__product').order_by('-created_at')
        # Find a sale by its number, the customer's name or phone, or what was sold.
        query = str(request.query_params.get('q') or '').strip()[:80]
        if query:
            rows = rows.filter(Q(number__icontains=query) | Q(customer__first_name__icontains=query) | Q(customer__last_name__icontains=query)
                               | Q(customer__in=CustomerProfile.objects.filter(phone__icontains=query).values('user_id')) | Q(items__variant__product__name__icontains=query)
                               | Q(items__variant__name__icontains=query)).distinct()
        # Only sales a customer still owes money on (after returns, price corrections and reversed payments).
        if request.query_params.get('owing') in {'1', 'true'}:
            rows = [s for s in rows.filter(status='COMPLETED') if sale_balance(s) > 0]
        count = len(rows) if isinstance(rows, list) else rows.count()
        # 'charged' is the amount after returns and price corrections; 'total' stays the original sale total.
        return Response({'count':count, 'results':[{'id':s.pk, 'number':s.number, 'total':s.total, 'created_at':s.created_at,
            'charged':sale_amounts(s)[0] if s.status=='COMPLETED' else Decimal(0),
            'customer':s.customer.get_full_name() or s.customer.username if s.customer else 'Walk-in',
            'customer_id':s.customer_id, 'status':s.status, 'due_date':s.due_date,
            'outstanding':max(Decimal(0), sale_balance(s)),
            'payments':[{'id':p.pk,'method':p.method,'amount':p.amount,'status':p.status,'reference':p.reference} for p in s.payments.all()],
            'items':[{'id':i.pk,'item':str(i.variant),'quantity':i.quantity,'list_price':i.list_price,'unit_price':i.unit_price,
                      'discount':i.discount,'net_amount':i.net_amount,'tax_amount':i.tax_amount,'returned_quantity':i.returned_quantity} for i in s.items.all()]}
            for s in rows[(page-1)*50:page*50]]})


class SaleCustomerView(APIView):
    """Names the customer who owes a Walk-in sale's unpaid balance (e.g. goods given on credit but rung up as paid,
    whose payment was then reversed). Only a sale with no customer yet can be given one; it never changes the amounts."""
    permission_classes = [HasLinTechPermission]
    permission_required = 'commerce.add_payment'
    @transaction.atomic
    def post(self, request, pk):
        from rest_framework.exceptions import ValidationError
        from apps.core.models import AuditLog
        sale = Sale.objects.select_for_update().get(pk=get_object_or_404(Sale, pk=pk).pk)
        if sale.customer_id:
            raise ValidationError('This sale already has a customer.')
        profile = CustomerProfile.objects.select_related('user').filter(user_id=request.data.get('customer_id')).first()
        if not profile:
            raise ValidationError('Choose a customer, or add them first.')
        sale.customer = profile.user
        sale.save(update_fields=['customer', 'updated_at'])
        AuditLog.objects.create(action='SALE_CUSTOMER_SET', object_type='Sale', object_id=str(sale.pk), user=request.user,
                                before={'customer': None}, after={'customer': profile.user_id, 'number': sale.number})
        return Response({'id': sale.pk, 'customer': profile.user.get_full_name() or profile.user.username})


class CollectionView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'commerce.add_payment'
    def post(self, request, pk):
        class Input(serializers.Serializer):
            amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('.01'))
            method = serializers.ChoiceField(choices=['CASH','BANK','MPESA','OTHER'])
            idempotency_key = serializers.CharField(max_length=100)
            reference = serializers.CharField(max_length=120, default='', allow_blank=True)
        form=Input(data=request.data);form.is_valid(raise_exception=True);d=form.validated_data
        payment=collect(sale=get_object_or_404(Sale,pk=pk), amount=d['amount'],method=d['method'],key=d['idempotency_key'],reference=d['reference'])
        return Response({'id':payment.pk,'status':payment.status},status=201)


class ConfirmPaymentView(APIView):
    permission_classes=[HasLinTechPermission]
    permission_required='commerce.change_payment'
    def post(self,request,pk):
        reference=serializers.CharField(max_length=120).run_validation(request.data.get('reference'))
        payment=get_object_or_404(Payment,pk=pk, sale__branch=request.store)
        payment=confirm_payment(payment=payment,reference=reference)
        return Response({'id':payment.pk,'status':payment.status})


class DismissPaymentView(APIView):
    """A waiting M-Pesa payment that never arrived or duplicates another payment: drop it."""
    permission_classes=[HasLinTechPermission]
    permission_required='commerce.change_payment'
    def post(self,request,pk):
        reason=serializers.CharField(max_length=240).run_validation(request.data.get('reason'))
        payment=get_object_or_404(Payment,pk=pk, sale__branch=request.store)
        payment=dismiss_payment(payment=payment,user=request.user,reason=reason)
        return Response({'id':payment.pk,'status':payment.status})


class PaymentReverseView(APIView):
    """A recorded payment that did not really happen, or not for that amount: it comes out of cash and the
    customer owes it again. Record what was actually paid as a new payment afterwards."""
    permission_classes=[HasLinTechPermission]
    permission_required='accounting.reverse_cashentry'
    @transaction.atomic
    def post(self,request,pk):
        from rest_framework.exceptions import ValidationError
        from apps.accounting.models import CashEntry
        from apps.accounting.services import reverse
        reason=str(request.data.get('reason') or '').strip()
        payment=get_object_or_404(Payment,pk=pk)
        if payment.status!='COMPLETED':
            raise ValidationError('Only a completed payment can be reversed.')
        entry=CashEntry.objects.filter(source_key=f'payment:{payment.pk}').first()
        if not entry:
            raise ValidationError('This payment has no cash-book entry to reverse.')
        reverse(entry=entry,user=request.user,reason=reason)
        payment.refresh_from_db()
        return Response({'id':payment.pk,'status':payment.status})


class DeletePaymentView(APIView):
    """Delete a payment that was not done right; record the right one again afterwards."""
    permission_classes=[HasLinTechPermission]
    permission_required='accounting.reverse_cashentry'
    def post(self,request,pk):
        reason=serializers.CharField(max_length=240).run_validation(request.data.get('reason'))
        payment=delete_payment(payment=get_object_or_404(Payment,pk=pk),user=request.user,reason=reason)
        return Response({'id':payment.pk,'status':payment.status})


class DeleteSaleView(APIView):
    """Delete a sale recorded by mistake; it comes out of that day's figures and can be recorded again."""
    permission_classes=[HasLinTechPermission]
    permission_required='commerce.change_sale'
    def post(self,request,pk):
        reason=serializers.CharField(max_length=240).run_validation(request.data.get('reason'))
        sale=delete_sale(sale=get_object_or_404(Sale,pk=pk),user=request.user,reason=reason)
        return Response({'id':sale.pk,'status':sale.status})


class ReturnSaleView(APIView):
    permission_classes=[HasLinTechPermission]
    permission_required='commerce.change_sale'
    def post(self,request,pk):
        reason=serializers.CharField(max_length=240).run_validation(request.data.get('reason'))
        sale=return_sale(sale=get_object_or_404(Sale,pk=pk),user=request.user,reason=reason)
        return Response({'id':sale.pk,'status':sale.status})


class SaleItemsReturnView(APIView):
    """Take back part of a sale; optionally refund the customer."""
    permission_classes=[HasLinTechPermission]
    permission_required='commerce.change_sale'
    def post(self,request,pk):
        from .returns import return_items
        sale_return=return_items(sale=get_object_or_404(Sale,pk=pk),lines=request.data.get('lines') or [],reason=str(request.data.get('reason') or ''),
            user=request.user,refund=request.data.get('refund') or None,idempotency_key=request.data.get('idempotency_key'))
        return Response({'id':sale_return.pk,'number':sale_return.number,'refund':sale_return.refund_amount},status=201)


class SaleNoteView(APIView):
    """A credit or debit note correcting a posted sale's price."""
    permission_classes=[HasLinTechPermission]
    permission_required='commerce.change_sale'
    def post(self,request,pk):
        from .models import SaleItem
        from .returns import adjust_sale_price
        sale=get_object_or_404(Sale,pk=pk)
        item=SaleItem.objects.filter(pk=request.data.get('item_id'),sale=sale).first() if request.data.get('item_id') else None
        note=adjust_sale_price(sale=sale,kind=str(request.data.get('kind') or '').upper(),amount=request.data.get('amount') or 0,
            reason=str(request.data.get('reason') or ''),user=request.user,item=item,idempotency_key=request.data.get('idempotency_key'))
        return Response({'id':note.pk,'kind':note.kind,'amount':note.amount},status=201)


class CustomersView(APIView):
    permission_classes=[HasLinTechPermission]
    def get_permissions(self):
        self.permission_required='accounts.view_customerprofile' if self.request.method=='GET' else 'accounts.add_customerprofile'
        return super().get_permissions()
    def get(self,request):
        rows=CustomerProfile.objects.select_related('user').filter(user__first_name__icontains=request.query_params.get('q',''))[:50]
        return Response([{'id':p.user_id,'name':p.user.get_full_name() or p.user.username,'phone':p.phone} for p in rows])
    @transaction.atomic
    def post(self,request):
        from uuid import uuid4
        class Input(serializers.Serializer):
            name=serializers.CharField(max_length=150)
            phone=serializers.CharField(max_length=30,allow_blank=True,default='')
        form=Input(data=request.data);form.is_valid(raise_exception=True)
        user=User.objects.create_user(username='customer-'+uuid4().hex,first_name=form.validated_data['name'],is_active=False)
        profile=CustomerProfile.objects.create(user=user,phone=form.validated_data['phone'])
        return Response({'id':user.pk,'name':user.first_name,'phone':profile.phone},status=201)
