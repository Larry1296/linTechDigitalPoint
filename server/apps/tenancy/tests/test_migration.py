"""Exercise the actual ownership backfill against historical migration models."""
from importlib import import_module
from decimal import Decimal
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

@pytest.mark.django_db(transaction=True)
def test_backfill_preserves_immutable_history_and_values():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    target = [('tenancy', '0002_assign_legacy_organization')]
    executor.migrate(target)
    state = executor.loader.project_state(target)
    apps = state.apps
    # The fresh test database has already passed the empty legacy migration.
    apps.get_model('tenancy','Organization').objects.filter(slug='lintech-digital-point').update(slug='empty-initial-business')
    User=apps.get_model('auth','User')
    user=User.objects.create(username='legacy-owner',is_staff=True,is_superuser=True,is_active=True)
    Store=apps.get_model('core','Store')
    Category=apps.get_model('catalog','Category')
    Product=apps.get_model('catalog','Product')
    Variant=apps.get_model('catalog','ProductVariant')
    Zone=apps.get_model('inventory','Zone')
    Shelf=apps.get_model('inventory','Shelf')
    Lot=apps.get_model('inventory','StockLot')
    Balance=apps.get_model('inventory','StockBalance')
    Adjustment=apps.get_model('inventory','StockAdjustment')
    Movement=apps.get_model('inventory','Movement')
    store=Store.objects.create(name='linTech Digital Point')
    category=Category.objects.create(name='Mobile Accessories',slug='mobile-accessories')
    product=Product.objects.create(name='Legacy product',slug='legacy',category=category)
    variant=Variant.objects.create(product=product,sku='LEGACY',selling_price=250)
    zone=Zone.objects.create(store=store,code='A',name='Legacy area')
    shelf=Shelf.objects.create(zone=zone,code='A1',display_name='Legacy shelf',x=0,y=0,width=10,height=10)
    lot=Lot.objects.create(variant=variant,reference='Historical receipt',received_quantity=12,remaining_quantity=10,unit_cost=Decimal('80.25'),received_at=timezone.now())
    balance=Balance.objects.create(lot=lot,shelf=shelf,quantity=10,reserved=1)
    adjustment=Adjustment.objects.create(variant=variant,shelf=shelf,quantity_before=11,amount=-1,quantity_after=10,reason='Lost item',performed_by=user,idempotency_key='historic-adjustment')
    movement=Movement.objects.create(variant=variant,lot=lot,source=shelf,quantity=1,movement_type='STOCK_ADJUSTMENT',reference='Historic',performed_by=user,adjustment=adjustment)
    sale=apps.get_model('commerce','Sale').objects.create(number='LEGACY-SALE',channel='POS',created_by=user,subtotal=250,total=250,cogs=Decimal('80.25'),gross_profit=Decimal('169.75'))
    item=apps.get_model('commerce','SaleItem').objects.create(sale=sale,variant=variant,quantity=1,unit_price=250,cost=Decimal('80.25'))
    payment=apps.get_model('commerce','Payment').objects.create(sale=sale,method='MPESA',amount=250,reference='LEGACY-PAYMENT',status='COMPLETED',idempotency_key='legacy-payment')
    allocation=apps.get_model('commerce','SaleAllocation').objects.create(item=item,lot=lot,shelf=shelf,quantity=1,unit_cost=Decimal('80.25'))
    receipt=apps.get_model('inventory','StockReceipt').objects.create(receipt_number='LEGACY-RECEIPT',received_at=timezone.now(),created_by=user)
    receipt_line=apps.get_model('inventory','StockReceiptLine').objects.create(receipt=receipt,variant=variant,received_quantity=12,unit_cost=Decimal('80.25'),lot=lot)
    account=apps.get_model('accounting','CashAccount').objects.create(name='Legacy cash',business_unit='SHOP',payment_method='CASH')
    entry=apps.get_model('accounting','CashEntry').objects.create(account=account,business_unit='SHOP',kind='EXPENSE',amount=-15,reference='LEGACY-EXPENSE',source_key='legacy-expense',created_by=user)
    expense_category=apps.get_model('accounting','ExpenseCategory').objects.create(name='Legacy expenses')
    expense=apps.get_model('accounting','Expense').objects.create(category=expense_category,business_unit='SHOP',entry=entry,description='Historical expense',created_by=user)
    records=[store,category,product,variant,zone,shelf,lot,balance,adjustment,movement,sale,item,payment,allocation,receipt,receipt_line,account,entry,expense_category,expense]
    before={ (obj._meta.label,obj.pk): type(obj).objects.values().get(pk=obj.pk) for obj in records }
    backfill=import_module('apps.tenancy.migrations.0002_assign_legacy_organization').backfill
    try:
        with connection.schema_editor() as editor:
            backfill(apps,editor)
        organization=apps.get_model('tenancy','Organization').objects.get(slug='lintech-digital-point')
        assert organization.owner_id == user.pk
        for obj in records:
            after=type(obj).objects.values().get(pk=obj.pk)
            assert after.pop('organization_id') == organization.pk
            old=before[(obj._meta.label,obj.pk)]; old.pop('organization_id')
            assert after == old
        for model in apps.get_models():
            if model._meta.app_label in {'core','accounts','catalog','inventory','commerce','cyber','mpesa','accounting'}:
                assert not model.objects.filter(organization_id=None).exists()
        with connection.cursor() as cursor:
            cursor.execute("SELECT tgenabled FROM pg_trigger WHERE tgname IN ('immutable_stock_adjustment','immutable_adjustment_movement')")
            assert all(row[0]=='O' for row in cursor.fetchall())
    finally:
        MigrationExecutor(connection).migrate(latest)
