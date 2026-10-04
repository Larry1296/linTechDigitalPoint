from decimal import Decimal
import pytest
from django.db import connection, transaction, IntegrityError
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.tenancy.context import organization_context, branch_context
from apps.core.models import Store
from apps.accounting.ledger import post_journal, paired, reverse_journal
from apps.accounting.models import JournalEntry, JournalLine, ExpenseCategory
from apps.accounting.services import record_expense
from apps.inventory.models import Zone, Shelf, StockBalance
from apps.inventory.services import complete_sale, receive_stock
from apps.tenancy.tests.test_isolation import businesses  # noqa: F401

pytestmark = pytest.mark.django_db


def test_sale_expense_reports_reconcile_and_pending_is_not_cash(businesses):
    a, b = businesses
    with organization_context(a['org']):
        a['variant'].selling_price = 1000
        a['variant'].save()
        a['lot'].unit_cost = 400
        a['lot'].save()
        sale = complete_sale(lines=[{'variant': a['variant'], 'quantity': 1}], channel='POS', number='ACCRUAL',
            user=a['user'], payment_method='MPESA', payment_status='MANUAL_REVIEW')
        category = ExpenseCategory.objects.create(name='Rent')
        expense = record_expense(user=a['user'], category=category, unit='SHOP', method='CASH', amount=200,
            description='Rent', key='rent')
        assert JournalEntry.objects.filter(source_key=f'sale:{sale.pk}').count() == 1
        assert not JournalEntry.objects.filter(source_key=f'payment:{sale.payments.get().pk}').exists()
        assert record_expense(user=a['user'], category=category, unit='SHOP', method='CASH', amount=200,
            description='Rent', key='rent').pk == expense.pk
        with pytest.raises(ValidationError):
            record_expense(user=a['user'], category=category, unit='SHOP', method='CASH', amount=201,
                description='Rent', key='rent')
    response = a['client'].get('/api/v1/accounting/ledger/reports/')
    assert response.status_code == 200, response.content
    report = response.json()
    assert {k: Decimal(v) for k, v in report['profit_loss'].items()} == {
        'revenue': 1000, 'cogs': 400, 'gross_profit': 600, 'expenses': 200, 'net_profit': 400}
    assert Decimal(report['debits']) == Decimal(report['credits'])
    assert Decimal(report['balance_sheet']['difference']) == 0
    assert Decimal(report['cash_movement']['net_movement']) == -200
    assert a['client'].get('/api/v1/accounting/ledger/reports/', {'branch': b['store'].pk}).status_code == 403


def test_journal_rejects_unbalanced_and_changed_retries_and_reverses(businesses):
    a = businesses[0]
    with organization_context(a['org']):
        with pytest.raises(ValidationError):
            post_journal(key='bad', description='Bad', lines=[('1000', 10, 0), ('3000', 0, 9)])
        kwargs = dict(key='manual:opening', description='Opening cash', lines=paired('1000', '3000', 100), user=a['user'])
        entry = post_journal(**kwargs)
        assert post_journal(**kwargs).pk == entry.pk
        with pytest.raises(ValidationError):
            post_journal(**{**kwargs, 'lines': paired('1000', '3000', 101)})
        correction = reverse_journal(entry, user=a['user'], reason='Wrong opening count')
        assert correction.reversal_of_id == entry.pk
        with pytest.raises(ValidationError):
            reverse_journal(entry, user=a['user'], reason='Again')
        with pytest.raises(IntegrityError), transaction.atomic():
            JournalLine.objects.filter(entry=entry).update(debit=200)
        with pytest.raises(IntegrityError), transaction.atomic():
            JournalEntry.objects.filter(pk=entry.pk).delete()


def test_branch_scoped_fifo_and_reports(businesses):
    a = businesses[0]
    with organization_context(a['org']):
        other = Store.objects.create(name='Second branch')
        zone = Zone.objects.create(store=other, code='SECOND', name='Second')
        shelf = Shelf.objects.create(zone=zone, code='SECOND', display_name='Second', x=0, y=0, width=1, height=1)
        with branch_context(other):
            receive_stock(variant=a['variant'], placements=[{'shelf': shelf, 'quantity': 2}], unit_cost=60,
                reference='SECOND', user=a['user'])
            sale = complete_sale(lines=[{'variant': a['variant'], 'quantity': 1}], channel='POS', number='SECOND-SALE', user=a['user'])
            assert sale.branch_id == other.pk
            assert sale.cogs == 60
            assert not StockBalance.objects.filter(shelf=a['shelf']).exists()
        with branch_context(a['store']):
            assert StockBalance.objects.get(shelf=a['shelf']).quantity == 5
            assert not JournalEntry.objects.filter(source_key=f'sale:{sale.pk}').exists()
    report = a['client'].get('/api/v1/accounting/ledger/reports/').json()
    assert Decimal(report['profit_loss']['revenue']) == 0
    report = a['client'].get('/api/v1/accounting/ledger/reports/', {'branch': other.pk}).json()
    assert Decimal(report['profit_loss']['revenue']) == 100


def test_database_checks_unbalanced_raw_journal(businesses):
    a = businesses[0]
    with organization_context(a['org']):
        with pytest.raises(IntegrityError), transaction.atomic():
            JournalEntry.objects.create(branch=a['store'], posting_date=timezone.localdate(), currency='KES',
                source_key='raw-bad', description='Unbalanced', fingerprint='x', created_by=a['user'])
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS balanced_journal IMMEDIATE')


def test_credit_partial_payment_confirmation_and_return(businesses):
    from apps.commerce.settlements import collect, confirm_payment, return_sale
    a = businesses[0]
    with organization_context(a['org']):
        sale = complete_sale(lines=[{'variant':a['variant'],'quantity':2}], channel='POS', number='CREDIT',
            paid_amount=0, idempotency_key='credit', user=a['user'])
        assert not sale.payments.exists()
        payment = collect(sale=sale, amount=50, method='CASH', key='partial')
        assert payment.status == 'COMPLETED'
        pending = collect(sale=sale, amount=150, method='MPESA', key='pending')
        assert not JournalEntry.objects.filter(source_key=f'payment:{pending.pk}').exists()
        confirm_payment(payment=pending, reference='PROVIDER-123')
        assert JournalEntry.objects.filter(source_key=f'payment:{pending.pk}').exists()
        assert confirm_payment(payment=pending, reference='PROVIDER-123').pk == pending.pk
        return_sale(sale=sale, user=a['user'], reason='Customer returned goods')
        assert StockBalance.objects.get(shelf=a['shelf']).quantity == 5
        assert return_sale(sale=sale, user=a['user'], reason='Retry').status == 'REFUNDED'
    report = a['client'].get('/api/v1/accounting/ledger/reports/').json()
    assert Decimal(report['profit_loss']['revenue']) == 0
    assert Decimal(report['profit_loss']['cogs']) == 0
    assert Decimal(report['cash_movement']['net_movement']) == 0


def test_receipt_without_shelves_posts_supplier_debt(businesses):
    a = businesses[0]
    response=a['client'].post('/api/v1/inventory/receipts/', {'supplier_name':'Supplier', 'external_reference':'INV-UNPLACED', 'idempotency_key':'unplaced',
        'lines':[{'variant_id':a['variant'].pk,'received_quantity':3,'unit_cost':40}]}, format='json')
    assert response.status_code in {200,201}, response.content
    with organization_context(a['org']):
        assert StockBalance.objects.get(shelf__is_virtual=True).quantity == 3
        assert JournalEntry.objects.filter(source_key__startswith='purchase:').exists()
    report=a['client'].get('/api/v1/accounting/ledger/reports/').json()
    # Fixture stock is also a purchase on credit (5 x 40).
    assert Decimal(report['balance_sheet']['liabilities']) == 320
    assert Decimal(report['cash_movement']['net_movement']) == 0


def test_opening_stock_and_transfer_preserve_business_value(businesses):
    from apps.inventory.services import create_product_with_opening_stock, transfer_stock
    a = businesses[0]
    with organization_context(a['org']):
        with branch_context(a['store']):
            _, variant = create_product_with_opening_stock(user=a['user'],
                product_data={'name':'Opening charger','category':a['category']},
                variant_data={'sku':'OPENING-CHARGER','selling_price':100},
                opening_quantity=4, opening_unit_cost=25)
            origin = StockBalance.objects.get(lot__variant=variant).shelf
            assert origin.is_virtual
        other = Store.objects.create(name='Transfer destination')
        zone = Zone.objects.create(store=other, code='T', name='Transfer')
        destination = Shelf.objects.create(zone=zone, code='T', display_name='Destination', x=0,y=0,width=1,height=1)
        transfer_stock(variant=variant, source=origin, destination=destination, quantity=2,
            reference='MOVE-2', user=a['user'])
        assert StockBalance.objects.get(shelf=origin, lot__variant=variant).quantity == 2
        assert StockBalance.objects.get(shelf=destination, lot__variant=variant).quantity == 2
        transfers = JournalLine.objects.filter(entry__source_key__startswith='transfer:')
        assert sum(line.debit-line.credit for line in transfers.filter(account__code='1250')) == 0
        assert sum(line.debit-line.credit for line in transfers.filter(account__code='1200', entry__branch=other)) == 50
        assert JournalEntry.objects.filter(source_key__startswith='opening-stock:').count() == 1
