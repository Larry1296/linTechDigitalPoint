"""Journal reports read only posted lines; every displayed number has a source."""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.permissions import HasLinTechPermission
from apps.tenancy.branches import authorized_stores
from apps.tenancy.context import branch_context
from apps.tenancy.models import Organization
from apps.tenancy.permissions import has_business_permission
from .models import JournalEntry, JournalLine, FinancialPeriod
from .ledger import post_journal, reverse_journal


class ReportInput(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(default=timezone.localdate)
    branch = serializers.IntegerField(min_value=1, required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    account = serializers.CharField(max_length=32, required=False)
    def validate(self, data):
        if data.get('start') and data['start'] > data['end']:
            raise serializers.ValidationError('Start must be on or before end.')
        return data


def report_scope(request, data):
    branches = authorized_stores(request.user, request.membership)
    selected = data.get('branch', getattr(request.store, 'pk', None))
    if not selected or not branches.filter(pk=selected).exists():
        raise PermissionDenied('Choose an authorized branch.')
    return selected


def balances(lines):
    return list(lines.values('account__code', 'account__name', 'account__kind', 'account__is_cash')
        .annotate(debit=Sum('debit'), credit=Sum('credit')).order_by('account__code'))


def totals(rows):
    result = {key: Decimal(0) for key in ['ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'COGS', 'EXPENSE']}
    for row in rows:
        result[row['account__kind']] += row['debit'] - row['credit']
    return result


def entry_data(entry):
    return {'id': entry.pk, 'posting_date': entry.posting_date, 'description': entry.description,
        'source_key': entry.source_key, 'currency': entry.currency, 'branch': entry.branch_id,
        'reversal_of': entry.reversal_of_id, 'lines': [{'account': line.account.code, 'name': line.account.name,
            'debit': line.debit, 'credit': line.credit} for line in entry.lines.select_related('account')]}


class LedgerReportView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'accounting.view_profit'
    def get(self, request):
        form = ReportInput(data=request.query_params)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        # Permission-checked branch override; SQL scoping still enforces organization.
        with branch_context(None):
            selected = report_scope(request, data)
        with branch_context(selected):
            history = JournalLine.objects.filter(entry__posting_date__lte=data['end'])
            period = history
            if data.get('start'):
                period = period.filter(entry__posting_date__gte=data['start'])
            trial = balances(period)
            period_totals = totals(trial)
            closing = totals(balances(history))
            revenue = -period_totals['REVENUE']
            cogs, expenses = period_totals['COGS'], period_totals['EXPENSE']
            earnings = -closing['REVENUE'] - closing['COGS'] - closing['EXPENSE']
            entries = JournalEntry.objects.filter(posting_date__lte=data['end'])
            if data.get('start'):
                entries = entries.filter(posting_date__gte=data['start'])
            if data.get('account'):
                entries = entries.filter(lines__account__code=data['account']).distinct()
            count = entries.count()
            offset = (data['page'] - 1) * 50
            cash = period.filter(account__is_cash=True).aggregate(amount=Sum(F('debit') - F('credit')))['amount'] or Decimal(0)
            opening_cash = Decimal(0)
            if data.get('start'):
                opening_cash = history.filter(entry__posting_date__lt=data['start'], account__is_cash=True).aggregate(
                    amount=Sum(F('debit') - F('credit')))['amount'] or Decimal(0)
            return Response({'basis': 'Posted double-entry journals only; historical opening balances may be incomplete.',
                'currency': request.organization.currency, 'branch': selected, 'filters': data,
                'profit_loss': {'revenue': revenue, 'cogs': cogs, 'gross_profit': revenue-cogs,
                    'expenses': expenses, 'net_profit': revenue-cogs-expenses},
                'balance_sheet': {'assets': closing['ASSET'], 'liabilities': -closing['LIABILITY'],
                    'equity': -closing['EQUITY'], 'retained_earnings': earnings,
                    'difference': closing['ASSET'] + closing['LIABILITY'] + closing['EQUITY'] - earnings},
                'trial_balance': trial, 'debits': sum((r['debit'] for r in trial), Decimal(0)),
                'credits': sum((r['credit'] for r in trial), Decimal(0)),
                'cash_movement': {'opening': opening_cash, 'net_movement': cash, 'closing': opening_cash+cash},
                'journals': {'count': count, 'page': data['page'], 'page_size': 50,
                    'results': [entry_data(e) for e in entries[offset:offset+50]]}})


class JournalView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'accounting.view_profit'
    def get(self, request, pk):
        return Response(entry_data(get_object_or_404(JournalEntry, pk=pk)))


class ManualJournalView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'accounting.post_manual_journal'
    def post(self, request):
        if request.membership.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}:
            raise PermissionDenied('An owner or accountant must post manual journals.')
        class Line(serializers.Serializer):
            account = serializers.CharField(max_length=32)
            debit = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0, default=0)
            credit = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0, default=0)
        class Input(serializers.Serializer):
            description = serializers.CharField(max_length=240)
            posting_date = serializers.DateField()
            idempotency_key = serializers.CharField(max_length=100)
            lines = Line(many=True, min_length=2, max_length=100)
        form = Input(data=request.data); form.is_valid(raise_exception=True)
        d = form.validated_data
        entry = post_journal(key='manual:'+d['idempotency_key'], description=d['description'], user=request.user,
            branch=request.store, date=d['posting_date'], lines=[(l['account'], l['debit'], l['credit']) for l in d['lines']])
        return Response(entry_data(entry), status=201)


class JournalReverseView(APIView):
    permission_classes = [HasLinTechPermission]
    permission_required = 'accounting.reverse_journal'
    def post(self, request, pk):
        if request.membership.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}:
            raise PermissionDenied('An owner or accountant must reverse journals.')
        entry = get_object_or_404(JournalEntry, pk=pk)
        if not entry.source_key.startswith('manual:'):
            raise ValidationError('Correct this entry through its source transaction so stock and payments stay consistent.')
        class Input(serializers.Serializer):
            reason = serializers.CharField(max_length=240)
            posting_date = serializers.DateField(default=timezone.localdate)
        form = Input(data=request.data); form.is_valid(raise_exception=True)
        result = reverse_journal(entry, user=request.user, reason=form.validated_data['reason'], date=form.validated_data['posting_date'])
        return Response(entry_data(result), status=201)
