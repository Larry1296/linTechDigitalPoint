from apps.tenancy.permissions import has_business_permission, is_business_manager
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from apps.core.permissions import HasLinTechPermission, IsInternalStaff
from apps.core.models import AuditLog, Store
from apps.catalog.models import ProductVariant
from apps.catalog.search import search_variants, variant_summary
from apps.inventory.models import StockReceipt, StockBalance
from apps.commerce.models import Sale, SaleItem
from apps.mpesa.models import MpesaReconciliation
from .models import JournalEntry, BusinessUnit, CashAccount, CashEntry, ExpenseCategory, Expense, Supplier, SupplierPurchase, PurchasePayment, DailyClosing, FinancialPeriod
from .services import record_expense, reverse, close_day, post, audit
from .reports import summary, home, stock_rows, filtered_entries


def serializer_for(model):
    class Serializer(serializers.ModelSerializer):
        class Meta:
            fields = '__all__'
    Serializer.Meta.model = model
    return Serializer


class BookPermission(HasLinTechPermission):
    def has_permission(self, request, view):
        model = view.queryset.model
        verb = 'view' if request.method in ['GET', 'HEAD', 'OPTIONS'] else 'add'
        view.permission_required = f'accounting.{verb}_{model._meta.model_name}'
        if getattr(view, 'action', '') == 'reverse':
            view.permission_required = 'accounting.reverse_cashentry'
        return super().has_permission(request, view)


class ReadBook(viewsets.ReadOnlyModelViewSet):
    permission_classes = [BookPermission]
    def get_serializer_class(self):
        return serializer_for(self.queryset.model)


class CreateBook(ReadBook):
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        audit(obj, request.user, 'Created book reference')
        return Response(serializer.data, status=201)


class SupplierViewSet(CreateBook):
    queryset = Supplier.objects.all().order_by('name')


class CategoryViewSet(CreateBook):
    queryset = ExpenseCategory.objects.all().order_by('name')


class AccountViewSet(CreateBook):
    queryset = CashAccount.objects.all().order_by('name')
    def list(self, request):
        return Response(list(self.queryset.annotate(balance=Sum('cashentry__amount', filter=Q(cashentry__in=CashEntry.objects.all()))).values('id', 'name', 'business_unit', 'payment_method', 'balance')))


class EntryViewSet(ReadBook):
    queryset = CashEntry.objects.all()
    def get_queryset(self):
        return filtered_entries(self.request.query_params)[0]
    def get_serializer_class(self):
        cls = serializer_for(CashEntry)
        if not has_business_permission(self.request.user, 'accounting.view_profit'):
            cls.Meta.fields = [f.name for f in CashEntry._meta.fields if f.name != 'cogs']
        return cls
    @action(detail=True, methods=['post'])
    def reverse(self, request, pk=None):
        result = reverse(entry=self.get_object(), user=request.user, reason=str(request.data.get('reason', '')))
        return Response(self.get_serializer(result).data, status=201)


class ExpenseInput(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=ExpenseCategory.objects.all())
    business_unit = serializers.ChoiceField(choices=BusinessUnit.choices)
    payment_method = serializers.ChoiceField(choices=['CASH', 'BANK', 'MPESA', 'OTHER'], required=False, default='CASH')
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    description = serializers.CharField(max_length=160)
    idempotency_key = serializers.CharField(max_length=100)
    paid = serializers.BooleanField(default=True)
    incurred_on = serializers.DateField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)


def expense_row(expense):
    from .services import expense_outstanding, expense_paid
    paid, outstanding = expense_paid(expense), expense_outstanding(expense)
    cancelled = JournalEntry.objects.filter(source_key=f'expense-cancel:{expense.pk}').exists()
    status = 'CANCELLED' if cancelled else 'PAID' if outstanding <= 0 else 'PARTLY_PAID' if paid > 0 else 'UNPAID'
    return {'id': expense.pk, 'description': expense.description, 'category': expense.category.name, 'business_unit': expense.business_unit,
            'amount': expense.amount, 'paid': paid, 'outstanding': max(Decimal('0'), outstanding), 'status': status,
            'incurred_on': expense.incurred_on, 'due_date': expense.due_date, 'entry': expense.entry_id,
            # Kept for older clients: "reversed" means the expense no longer counts.
            'date': expense.incurred_on, 'reversed': cancelled}


class ExpenseViewSet(ReadBook):
    queryset = Expense.objects.select_related('entry', 'category').all().order_by('-incurred_on', '-pk')
    def list(self, request):
        rows = self.queryset
        start, end = request.query_params.get('start'), request.query_params.get('end')
        if start:
            rows = rows.filter(incurred_on__gte=serializers.DateField().run_validation(start))
        if end:
            rows = rows.filter(incurred_on__lte=serializers.DateField().run_validation(end))
        return Response([expense_row(e) for e in rows[:500]])
    def create(self, request):
        form = ExpenseInput(data=request.data); form.is_valid(raise_exception=True)
        d = form.validated_data
        obj = record_expense(user=request.user, category=d['category'], unit=d['business_unit'], method=d['payment_method'],
            amount=d['amount'], description=d['description'], key=d['idempotency_key'], paid=d['paid'],
            incurred_on=d.get('incurred_on'), due_date=d.get('due_date'))
        return Response(expense_row(obj), status=201)
    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        from .services import pay_expense
        if not has_business_permission(request.user, 'accounting.add_expense'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        class Input(serializers.Serializer):
            amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
            payment_method = serializers.ChoiceField(choices=['CASH', 'BANK', 'MPESA', 'OTHER'])
            idempotency_key = serializers.CharField(max_length=100)
        form = Input(data=request.data); form.is_valid(raise_exception=True); d = form.validated_data
        expense = self.get_object()
        pay_expense(expense=expense, amount=d['amount'], method=d['payment_method'], key=d['idempotency_key'], user=request.user)
        return Response(expense_row(expense), status=201)
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from .services import cancel_expense
        if not has_business_permission(request.user, 'accounting.reverse_cashentry'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        expense = self.get_object()
        cancel_expense(expense=expense, user=request.user, reason=str(request.data.get('reason') or ''))
        return Response(expense_row(expense))


class PurchaseViewSet(ReadBook):
    queryset = SupplierPurchase.objects.select_related('receipt', 'supplier').all().order_by('-pk')
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def pay(self, request, pk=None):
        if not has_business_permission(request.user, 'accounting.add_purchasepayment'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        from apps.tenancy.transactions import lock_business
        lock_business()
        purchase = SupplierPurchase.objects.select_for_update().get(pk=self.get_object().pk)
        class Input(serializers.Serializer):
            amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
            payment_method = serializers.ChoiceField(choices=['CASH', 'BANK', 'MPESA', 'OTHER'])
            idempotency_key = serializers.CharField(max_length=100)
        form = Input(data=request.data); form.is_valid(raise_exception=True); d = form.validated_data
        from .services import pay_purchase
        replay = CashEntry.objects.filter(source_key=f"purchase:{d['idempotency_key']}").exists()
        entry = pay_purchase(purchase=purchase, amount=d['amount'], method=d['payment_method'], key=d['idempotency_key'], user=request.user)
        return Response({'entry': entry.pk}, status=200 if replay else 201)


class ClosingViewSet(ReadBook):
    queryset = DailyClosing.objects.all().order_by('-date')
    def create(self, request):
        class Input(serializers.Serializer):
            account = serializers.PrimaryKeyRelatedField(queryset=CashAccount.objects.all())
            date = serializers.DateField()
            actual = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=0)
            reason = serializers.CharField(allow_blank=True, default='')
        form = Input(data=request.data); form.is_valid(raise_exception=True)
        obj = close_day(user=request.user, **form.validated_data)
        return Response(self.get_serializer(obj).data, status=201)


class PeriodViewSet(CreateBook):
    queryset = FinancialPeriod.objects.all().order_by('-start')
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def close(self, request, pk=None):
        if not has_business_permission(request.user, 'accounting.change_financialperiod'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        if request.membership.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('An owner or accountant must close periods.')
        from apps.tenancy.models import Organization
        Organization.objects.select_for_update().get(pk=request.organization.pk)
        obj = FinancialPeriod.objects.select_for_update().get(pk=self.get_object().pk)
        if obj.end >= timezone.localdate():
            raise ValidationError('Only past financial periods can be closed.')
        before = {'closed': obj.closed}
        obj.closed = True; obj.save(update_fields=['closed'])
        audit(obj, request.user, 'Period closed', before)
        return Response(self.get_serializer(obj).data)


class HomeView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = "accounting.view_cashentry"
    def get(self, request):
        return Response(home(request.user))


class ReportView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'accounting.view_cashentry'
    def get(self, request):
        data = summary(request.user, request.query_params)
        entries, filters = filtered_entries(request.query_params)
        data['stock'] = stock_rows(request.user)
        from .supplier_settlement import real_purchases
        purchases = real_purchases().select_related('receipt')
        closings = DailyClosing.objects.select_related('account')
        reconciliation = MpesaReconciliation.objects.all()
        sales = SaleItem.objects.select_related('sale', 'variant__product').filter(sale__status='COMPLETED')
        for key, lookup in [('start', 'gte'), ('end', 'lte')]:
            if key in filters:
                purchases = purchases.filter(**{f'receipt__received_at__date__{lookup}': filters[key]})
                closings = closings.filter(**{f'date__{lookup}': filters[key]})
                reconciliation = reconciliation.filter(**{f'created_at__date__{lookup}': filters[key]})
                sales = sales.filter(**{f'sale__created_at__date__{lookup}': filters[key]})
        if 'employee' in filters:
            purchases = purchases.filter(created_by_id=filters['employee']); closings = closings.filter(created_by_id=filters['employee'])
            reconciliation = reconciliation.filter(operator_id=filters['employee']); sales = sales.filter(sale__created_by_id=filters['employee'])
        if 'business_unit' in filters:
            unit = filters['business_unit']; purchases = purchases.filter(business_unit=unit); closings = closings.filter(account__business_unit=unit)
            if unit != 'MPESA': reconciliation = reconciliation.none()
            sales = sales.filter(sale__channel='CYBER') if unit == 'CYBER' else sales.exclude(sale__channel='CYBER') if unit == 'SHOP' else sales.none()
        if 'payment_method' in filters:
            method = filters['payment_method']; purchases = purchases.filter(payments__entry__account__payment_method=method).distinct()
            closings = closings.filter(account__payment_method=method); sales = sales.filter(sale__payments__method=method).distinct()
            if method not in ['AGENCY_CASH', 'AGENCY_FLOAT']: reconciliation = reconciliation.none()
        data['purchases'] = list(purchases.values('id', 'receipt_id', 'receipt__receipt_number', 'supplier__name', 'amount', 'payment_source'))
        data['closings'] = list(closings.values('date', 'account__name', 'expected', 'actual', 'discrepancy', 'reason'))
        data['mpesa_reconciliation'] = list(reconciliation.values('session_id', 'expected_cash', 'actual_cash', 'cash_variance', 'expected_float', 'actual_float', 'float_variance'))
        data['product_history'] = [{'reference': i.sale.number, 'product': str(i.variant), 'quantity': i.quantity, 'revenue': i.net_amount,
            **({'cost': i.cost, 'gross_profit': i.net_amount-i.cost} if has_business_permission(request.user, 'accounting.view_profit') else {})} for i in sales]
        data['cashbook'] = list(entries.values('id', 'occurred_at', 'reference', 'business_unit', 'kind', 'amount', 'account__name'))
        return Response(data)


class SearchView(APIView):
    permission_classes = [IsInternalStaff]
    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 2: return Response([])
        results = []
        if has_business_permission(request.user, 'catalog.view_product') or has_business_permission(request.user, 'cyber.view_cyberjob'):
            variants = search_variants(ProductVariant.objects.filter(active=True).select_related('product__category', 'product__brand'), q)
            if not has_business_permission(request.user, 'catalog.view_product'):
                variants = variants.filter(cyber_profile__isnull=False)
            for v in variants[:12]:
                row = variant_summary(v)
                balances = StockBalance.objects.filter(lot__variant=v, quantity__gt=0)
                row.update(type='product', label=str(v), url='/products' if v.product.product_type == 'STOCK_ITEM' else '/cyber/services',
                    available=balances.aggregate(v=Sum(F('quantity')-F('reserved')))['v'] or 0,
                    shelf=', '.join(balances.values_list('shelf__code', flat=True).distinct()))
                if has_business_permission(request.user, 'accounting.view_profit'):
                    lot = v.lots.filter(pk__in=StockBalance.objects.values("lot_id")).order_by('-received_at', '-pk').first()
                    row['latest_buying_cost'] = lot.unit_cost if lot else v.service_cost
                results.append(row)
        for model, perm, field, url in [(Supplier, 'accounting.view_supplier', 'name', '/suppliers'),
                (StockReceipt, 'inventory.view_stockreceipt', 'receipt_number', '/receipts'),
                (Sale, 'commerce.view_sale', 'number', '/sales-history')]:
            if has_business_permission(request.user, perm):
                results.extend({'type': model._meta.model_name, 'id': r.pk, 'label': getattr(r, field), 'url': f'{url}/{r.pk}' if model == StockReceipt else url}
                    for r in model.objects.filter(**{field+'__icontains': q})[:6])
        return Response(results)


class AdministrationView(APIView):
    permission_classes = [HasLinTechPermission]
    def get(self, request, section):
        required = {'users': 'accounts.view_customerprofile', 'audit': 'core.view_auditlog', 'settings': 'core.view_store'}
        if section not in required:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        if not has_business_permission(request.user, required[section]):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        if section == 'users':
            return Response(list(get_user_model().objects.filter(memberships__organization_id=request.organization.pk).values('id', 'username', 'first_name', 'is_active')))
        if section == 'audit':
            return Response(list(AuditLog.objects.values('id', 'user__username', 'created_at', 'action', 'object_type', 'before', 'after')[:200]))
        return Response(list(Store.objects.values('name', 'currency', 'timezone', 'address', 'phone', 'receipt_footer')))


class ExportView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'accounting.view_cashentry'
    def get(self, request):
        import csv
        from io import StringIO
        from django.http import HttpResponse
        entries, _ = filtered_entries(request.query_params)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Reference', 'Business unit', 'Kind', 'Amount', 'Account'])
        def safe_text(value):
            value = str(value)
            return "'" + value if value.startswith(('=', '+', '-', '@')) else value
        for entry in entries:
            writer.writerow([entry.occurred_at.isoformat(), safe_text(entry.reference), entry.business_unit,
                             entry.kind, entry.amount, safe_text(entry.account.name)])
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="business-cashbook.csv"'
        return response
