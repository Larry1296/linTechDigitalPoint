from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError as APIValidationError
from apps.tenancy.context import branch_context, organization_context
from apps.tenancy.models import Organization, Membership, OrganizationSubscription
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.models import Zone, Shelf, StockBalance, StockLot
from apps.inventory.services import receive_stock, complete_sale, transfer_stock

pytestmark = pytest.mark.django_db

@pytest.fixture
def businesses():
    rows = []
    for label in ['Alpha', 'Beta']:
        user = User.objects.create_user(label, password='Safe-pass-1848')
        org = Organization.objects.create(name=label, slug=label.lower(), owner=user)
        Membership.objects.create(user=user, organization=org, role='OWNER')
        OrganizationSubscription.objects.create(organization=org, status='ACTIVE')
        with organization_context(org):
            store = Store.objects.create(name=label)
            category = Category.objects.create(name=f'{label} category', slug='common')
            product = Product.objects.create(name=f'{label} private product', slug='common', category=category, ecommerce_visible=False)
            variant = ProductVariant.objects.create(product=product, sku='COMMON', selling_price=100)
            zone = Zone.objects.create(store=store, name=label, code='A')
            shelf = Shelf.objects.create(zone=zone, code='S1', display_name=label, x=0, y=0, width=10, height=10)
            lot = receive_stock(variant=variant, placements=[{'shelf': shelf, 'quantity': 5}], unit_cost=40, reference='SAME', user=user)
        client = APIClient()
        client.force_login(user)
        rows.append(dict(user=user, org=org, category=category, product=product, variant=variant, store=store, zone=zone, shelf=shelf, lot=lot, client=client))
    return rows


def test_no_context_is_fail_closed(businesses):
    assert Category.objects.count() == 0
    with pytest.raises(ValidationError):
        Category.objects.create(name='No tenant', slug='none')


def test_reusable_querysets_bind_at_execution(businesses):
    query = Category.objects.filter(slug='common')
    a, b = businesses
    with organization_context(a['org']):
        assert list(query.values_list('pk', flat=True)) == [a['category'].pk]
    with organization_context(b['org']):
        assert list(query.values_list('pk', flat=True)) == [b['category'].pk]
    assert not query.exists()

@pytest.mark.parametrize('path,key', [('catalog/categories/','category'), ('catalog/products/','product'), ('catalog/variants/','variant'), ('locations/zones/','zone'), ('locations/shelves/','shelf')])
def test_list_retrieve_update_delete_isolated(businesses, path, key):
    a,b=businesses
    client=a['client']; other=b[key].pk
    response=client.get('/api/v1/'+path)
    assert response.status_code == 200, response.content
    assert 'Beta' not in response.content.decode()
    for method, data in [('get', {}), ('patch', {'name': 'Changed'}), ('delete', {})]:
        response=getattr(client,method)(f'/api/v1/{path}{other}/', data, format='json')
        assert response.status_code in {400,404}, response.content


def test_cross_tenant_nested_create_and_update(businesses):
    a,b=businesses
    response=a['client'].patch(f"/api/v1/catalog/products/{a['product'].pk}/", {'category': b['category'].pk}, format='json')
    assert response.status_code == 400, response.content
    with organization_context(a['org']):
        with pytest.raises(ValidationError):
            Product.objects.create(name='Bad', slug='bad', category=b['category'])
        with pytest.raises(IntegrityError), transaction.atomic():
            Product.objects.filter(pk=a['product'].pk).update(category_id=b['category'].pk)


def test_database_rejects_raw_cross_tenant_foreign_key(businesses):
    a,b=businesses
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('UPDATE catalog_product SET category_id=%s WHERE id=%s', [b['category'].pk,a['product'].pk])


def test_search_reports_and_analytics(businesses):
    a,b=businesses
    for path in ['commerce/pos/catalog/?q=Beta', 'store/search-suggestions/?q=Beta', 'accounting/home/', 'accounting/reports/']:
        response=a['client'].get('/api/v1/'+path)
        assert response.status_code == 200, (path,response.content)
        assert 'Beta' not in response.content.decode()


def test_switch_validates_membership_and_clears_branch(businesses):
    a,b=businesses; client=a['client']
    assert client.post('/api/v1/tenancy/select/', {'organization_id':b['org'].pk}, format='json').status_code == 403
    Membership.objects.create(user=a['user'], organization=b['org'], role='READ_ONLY')
    assert client.post('/api/v1/tenancy/select/', {'organization_id':b['org'].pk}, format='json').status_code == 200
    response=client.get('/api/v1/catalog/categories/')
    assert 'Beta' in response.content.decode() and 'Alpha' not in response.content.decode()


def test_suspended_membership_and_global_superuser_do_not_bypass(businesses):
    a,b=businesses
    Membership.objects.filter(user=a['user']).update(status='SUSPENDED')
    User.objects.filter(pk=a['user'].pk).update(is_staff=True,is_superuser=True)
    assert a['client'].get('/api/v1/catalog/products/').status_code == 403
    assert b['client'].get('/platform-admin/').status_code in {302,403}


def test_subscriptions_and_modules_are_enforced(businesses):
    a,_=businesses
    OrganizationSubscription.objects.filter(organization=a['org']).update(status='EXPIRED')
    assert a['client'].get('/api/v1/catalog/categories/').status_code == 200
    assert a['client'].post('/api/v1/catalog/categories/', {'name':'Blocked'}, format='json').status_code == 403
    Organization.objects.filter(pk=a['org'].pk).update(enabled_modules=[])
    assert a['client'].get('/api/v1/catalog/categories/').status_code == 403


def test_fifo_sale_and_cross_tenant_transfer_rollback(businesses):
    a,b=businesses
    with organization_context(a['org']):
        with pytest.raises(APIValidationError):
            transfer_stock(variant=a['variant'],source=a['shelf'],destination=b['shelf'],quantity=1,reference='bad',user=a['user'])
        assert StockBalance.objects.get(lot=a['lot']).quantity == 5
        sale=complete_sale(lines=[{'variant':a['variant'],'quantity':2}],channel='POS',number='SALE',user=a['user'])
        assert sale.cogs == Decimal('80')
        assert StockBalance.objects.get(lot=a['lot']).quantity == 3
    with organization_context(b['org']):
        assert StockBalance.objects.get(lot=b['lot']).quantity == 5
        assert StockLot.objects.get(pk=b['lot'].pk).remaining_quantity == 5


def test_public_metadata_contains_no_tenant(businesses):
    response=APIClient().get('/api/v1/tenancy/platform/')
    assert response.status_code == 200
    assert 'Alpha' not in response.content.decode() and 'Beta' not in response.content.decode()
    assert APIClient().get('/api/v1/accounting/home/').status_code == 403

@pytest.fixture
def operations(businesses):
    from django.utils import timezone
    from apps.cyber.models import CyberServiceProfile
    from apps.cyber.services import create_job, complete_job
    from apps.mpesa.models import MpesaOutlet
    from apps.mpesa.services import open_session, post_transaction
    from apps.accounting.models import ExpenseCategory
    from apps.accounting.services import record_expense
    from apps.inventory.models import StockReceipt, StockReceiptLine
    from apps.accounts.models import CustomerProfile
    for business in businesses:
        with organization_context(business['org']):
            name=business['org'].name
            business['customer']=CustomerProfile.objects.create(user=business['user'], phone=name)
            product=Product.objects.create(name=f'{name} service', slug='service', category=business['category'],product_type='SERVICE')
            variant=ProductVariant.objects.create(product=product, sku='SERVICE', selling_price=25)
            business['service']=CyberServiceProfile.objects.create(variant=variant,billing_unit='FIXED')
            business['job']=create_job(user=business['user'],lines=[{'variant_id':variant.pk,'quantity':2}])
            business['sale']=complete_job(job=business['job'],user=business['user'],payment_method='CASH')
            business['outlet']=MpesaOutlet.objects.create(store=business['store'],display_name=name)
            business['session']=open_session(outlet=business['outlet'],operator=business['user'],opening_cash=1000,opening_float=1000)
            business['transaction'],_=post_transaction(session=business['session'],transaction_type='CUSTOMER_DEPOSIT',customer_name='Jane Wanjiru', customer_phone='0712345678', customer_id_number='12345678',transaction_amount=100,user=business['user'],idempotency_key='SAME',provider_reference='SHARED-REFERENCE')
            category=ExpenseCategory.objects.create(name=name)
            business['expense']=record_expense(user=business['user'],category=category,unit='SHOP',method='CASH',amount=10,description=f'{name} expense',key='SAME')
            business['receipt']=StockReceipt.objects.create(receipt_number='SAME',received_at=timezone.now(),created_by=business['user'])
            StockReceiptLine.objects.create(receipt=business['receipt'],variant=business['variant'],received_quantity=5,unit_cost=40,lot=business['lot'])
    return businesses

@pytest.mark.parametrize('path,key', [('cyber/services/','service'),('cyber/jobs/','job'),('mpesa/outlets/','outlet'),('mpesa/sessions/','session'),('mpesa/transactions/','transaction'),('accounting/expenses/','expense')])
def test_operating_records_list_and_retrieve_isolation(operations,path,key):
    a,b=operations
    response=a['client'].get('/api/v1/'+path)
    assert response.status_code == 200, response.content
    assert 'Beta' not in response.content.decode()
    response=a['client'].get(f"/api/v1/{path}{b[key].pk}/")
    assert response.status_code == 404, response.content


def test_receipts_payments_staff_customers_and_export(operations):
    from apps.commerce.models import Payment
    from apps.accounts.models import CustomerProfile
    a,b=operations
    assert a['client'].get(f"/api/v1/inventory/receipts/{b['receipt'].pk}/").status_code == 404
    export=a['client'].get('/api/v1/accounting/export/')
    assert export.status_code == 200 and 'Alpha' in export.content.decode() and 'Beta' not in export.content.decode()
    report=a['client'].get('/api/v1/accounting/reports/').json()
    assert Decimal(str(report['totals']['revenue'])) == Decimal('50.00')
    assert 'Beta' not in str(report)
    staff=a['client'].get('/api/v1/accounting/administration/users/').json()
    assert [row['id'] for row in staff] == [a['user'].pk]
    with organization_context(a['org']):
        assert list(CustomerProfile.objects.values_list('pk',flat=True)) == [a['customer'].pk]
        assert not Payment.objects.filter(sale_id=b['sale'].pk).exists()
        assert not Payment.objects.filter(sale_id=b['sale'].pk).update(reference='Changed')
        assert not Payment.objects.filter(sale_id=b['sale'].pk).delete()[0]


def test_service_snapshots_and_no_stock_effect(operations):
    from apps.cyber.models import CyberJobLine
    from apps.cyber.services import create_job
    from rest_framework.exceptions import ValidationError as APIValidationError
    a,b=operations
    with organization_context(a['org']):
        assert StockBalance.objects.get(lot=a['lot']).quantity == 5
        variant=a['service'].variant
        variant.selling_price=200; variant.save()
        assert CyberJobLine.objects.get(job=a['job']).unit_price == 25
        Membership.objects.filter(user=a['user'],organization=a['org']).update(role='SERVICE_ATTENDANT')
        with pytest.raises(APIValidationError):
            create_job(user=a['user'],lines=[{'variant_id':variant.pk,'unit_price':1}])
        with pytest.raises(ProductVariant.DoesNotExist):
            create_job(user=a['user'],lines=[{'variant_id':b['service'].variant_id}])


def test_mpesa_duplicates_and_cross_tenant_session(operations):
    from apps.mpesa.services import post_transaction
    from rest_framework.exceptions import ValidationError as APIValidationError
    a,b=operations
    with organization_context(a['org']):
        with pytest.raises(APIValidationError):
            post_transaction(session=a['session'],transaction_type='CUSTOMER_DEPOSIT',customer_name='Jane Wanjiru', customer_phone='0712345678', customer_id_number='12345678',transaction_amount=50,user=a['user'],idempotency_key='OTHER',provider_reference='SHARED-REFERENCE')
    response=a['client'].post('/api/v1/mpesa/transactions/',{'session':b['session'].pk,'transaction_type':'CUSTOMER_DEPOSIT','amount':10,'idempotency_key':'bad'},format='json')
    assert response.status_code == 404, response.content


def test_configured_plan_limits(businesses):
    from apps.tenancy.models import SubscriptionPlan
    a,b=businesses
    plan=SubscriptionPlan.objects.create(name='Configured plan',user_limit=1,branch_limit=1)
    OrganizationSubscription.objects.filter(organization=a['org']).update(plan=plan)
    with pytest.raises(ValidationError):
        Membership.objects.create(organization=a['org'],user=b['user'],role='CASHIER')
    with organization_context(a['org']), pytest.raises(ValidationError):
        Store.objects.create(name='Second branch')


def test_registration_onboarding_and_session_refresh():
    client=APIClient()
    response=client.post('/api/v1/tenancy/register/',{'first_name':'Wanjiru','last_name':'Kamau','phone':'0712 345 678','password_confirm':'New-strong-pass-2935','username':'new-business-owner','email':'owner@example.test','password':'New-strong-pass-2935'},format='json')
    assert response.status_code == 201, response.content
    client.credentials(HTTP_AUTHORIZATION='Bearer '+response.json()['access_token'])
    assert client.get('/api/v1/auth/me/').json()['organization'] is None
    assert client.get('/api/v1/inventory/dashboard/').status_code == 403
    created=client.post('/api/v1/tenancy/create/',{'name':'New Business','business_type':'Boutique','enabled_modules':['inventory','pos'],'currency':'USD','timezone':'America/New_York'},format='json')
    assert created.status_code == 201, created.content
    me=client.get('/api/v1/auth/me/').json()
    assert me['organization']['name'] == 'New Business'
    assert me['organization']['currency'] == 'USD'
    assert me['roles'] == ['OWNER'] and not me['platform_admin']
    assert client.get('/api/v1/catalog/categories/').json() == []
    assert client.post('/api/v1/auth/refresh/').status_code == 200
    assert client.post('/api/v1/auth/logout/').status_code == 204
    assert client.get('/api/v1/catalog/products/').status_code == 401


def test_platform_admin_created_business_starts_active_not_trial():
    admin = User.objects.create_user('platform-admin', password='Safe-pass-1848', is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_login(admin)
    created = client.post('/api/v1/tenancy/create/', {'name': 'Admin Business', 'enabled_modules': ['inventory']}, format='json')
    assert created.status_code == 201, created.content
    org = Organization.objects.get(name='Admin Business')
    assert org.subscription.status == 'ACTIVE'


def test_regular_signup_created_business_still_starts_trial():
    owner = User.objects.create_user('regular-owner', password='Safe-pass-1848')
    client = APIClient()
    client.force_login(owner)
    created = client.post('/api/v1/tenancy/create/', {'name': 'Customer Business', 'enabled_modules': ['inventory']}, format='json')
    assert created.status_code == 201, created.content
    org = Organization.objects.get(name='Customer Business')
    assert org.subscription.status == 'TRIAL'


def test_bulk_upsert_cannot_update_another_business(businesses):
    a, b = businesses
    with organization_context(a['org']), pytest.raises(ValidationError):
        Category.objects.bulk_create(
            [Category(pk=b['category'].pk, name='Overwritten', slug='replacement')],
            update_conflicts=True, update_fields=['name'], unique_fields=['pk'],
        )
    with organization_context(b['org']):
        assert Category.objects.get(pk=b['category'].pk).name == 'Beta category'


def test_stale_browser_business_cannot_read_or_write_after_switch(businesses):
    a, b = businesses
    Membership.objects.create(user=a['user'], organization=b['org'], role='OWNER')
    client = a['client']
    assert client.post('/api/v1/tenancy/select/', {'organization_id': b['org'].pk}, format='json').status_code == 200
    headers = {'HTTP_X_ORGANIZATION_ID': str(a['org'].pk)}
    for method, path, data in [
        ('get', 'catalog/categories/', {}),
        ('post', 'catalog/categories/', {'name': 'Stale category'}),
        ('get', 'accounting/export/', {}),
        ('get', 'inventory/dashboard/', {}),
    ]:
        response = getattr(client, method)('/api/v1/' + path, data, format='json', **headers)
        assert response.status_code == 409
        assert response.json()['code'] == 'organization_changed'
    with organization_context(b['org']):
        assert not Category.objects.filter(name='Stale category').exists()
    response = client.get('/api/v1/catalog/categories/', HTTP_X_ORGANIZATION_ID=str(b['org'].pk))
    assert response.status_code == 200 and 'Beta' in response.content.decode()


def test_customer_reverse_join_does_not_infer_jobs_from_other_business(businesses):
    from apps.accounts.models import CustomerProfile
    from apps.cyber.models import CyberJob
    a, b = businesses
    assert a['client'].get('/api/v1/cyber/dashboard/').status_code == 200
    Membership.objects.create(user=a['user'], organization=b['org'], role='READ_ONLY')
    with organization_context(a['org']):
        CustomerProfile.objects.create(user=a['user'])
    with organization_context(b['org']):
        CyberJob.objects.create(number='PRIVATE', customer=a['user'])
    response = a['client'].get('/api/v1/cyber/dashboard/')
    assert response.status_code == 200
    assert response.json()['recent_customers'] == []


@pytest.mark.parametrize('quantity', [0, -1, 'NaN', 'Infinity', 'invalid'])
def test_invalid_pos_quantity_rolls_back_stock_and_financial_records(businesses, quantity):
    from apps.commerce.models import Sale, Payment
    a, _ = businesses
    response = a['client'].post('/api/v1/commerce/pos/complete/', {'items': [{'variant_id': a['variant'].pk, 'quantity': quantity}]}, format='json')
    assert response.status_code == 400, response.content
    with organization_context(a['org']):
        assert StockBalance.objects.get(lot=a['lot']).quantity == 5
        assert not Sale.objects.exists() and not Payment.objects.exists()


def test_cashier_cannot_read_financial_overview_or_checkout_costs(businesses):
    a, _ = businesses
    Membership.objects.filter(user=a['user']).update(role='CASHIER')
    assert a['client'].get('/api/v1/accounting/home/').status_code == 403
    response = a['client'].post('/api/v1/commerce/pos/complete/', {'items': [{'variant_id': a['variant'].pk, 'quantity': 1}]}, format='json')
    assert response.status_code == 201, response.content
    assert 'cogs' not in response.json() and 'gross_profit' not in response.json()



def test_anyone_bargains_down_to_the_buying_price_and_below_the_lowest_price_is_logged(businesses):
    from apps.commerce.models import Sale
    from apps.core.models import AuditLog
    a, _ = businesses
    with organization_context(a['org']):
        ProductVariant.objects.filter(pk=a['variant'].pk).update(minimum_price=80)  # sells at 100; the stock cost 40
    Membership.objects.filter(user=a['user']).update(role='CASHIER')
    sell = lambda **line: a['client'].post('/api/v1/commerce/pos/complete/', {'items': [{'variant_id': a['variant'].pk, 'quantity': 1, **line}]}, format='json')
    assert sell(unit_price='85').status_code == 201
    assert sell(unit_price='50').status_code == 201  # below the lowest price, still above what it cost
    too_low = sell(unit_price='30')
    assert too_low.status_code == 400 and 'below what the item cost' in too_low.json()['detail']
    assert '40' not in too_low.json()['detail']  # a cashier is not shown the buying price
    assert sell(unit_price='120').status_code == 403  # above the asking price is a manager's call
    assert sell(discount='10', discount_reason='x').status_code == 403
    Membership.objects.filter(user=a['user']).update(role='OWNER')
    assert sell(unit_price='45').status_code == 201  # no reason needed
    owner_low = sell(unit_price='30')
    assert owner_low.status_code == 400 and 'below buying cost' in str(owner_low.json())
    with organization_context(a['org']):
        assert Sale.objects.count() == 3
        assert AuditLog.objects.filter(action='SALE_BELOW_MINIMUM_PRICE').count() == 2
        assert StockBalance.objects.get(lot=a['lot']).quantity == 2  # refused sales took no stock


def test_a_part_paid_till_sale_must_name_the_customer_who_owes_the_balance(businesses):
    from apps.commerce.models import Payment, Sale
    a, _ = businesses
    sale = {'items': [{'variant_id': a['variant'].pk, 'quantity': 1}], 'paid_amount': '60', 'due_date': '2026-09-26'}
    refused = a['client'].post('/api/v1/commerce/pos/complete/', sale, format='json')
    assert refused.status_code == 400 and '40.00 will still be owed' in str(refused.json())
    customer = a['client'].post('/api/v1/commerce/customers/', {'name': 'Jane Wanjiku', 'phone': '0712345678'}, format='json').json()
    assert a['client'].post('/api/v1/commerce/pos/complete/', {**sale, 'customer_id': customer['id']}, format='json').status_code == 201
    with organization_context(a['org']):
        assert Sale.objects.get().customer_id == customer['id'] and Payment.objects.get().amount == 60
        assert StockBalance.objects.get(lot=a['lot']).quantity == 4

def test_without_a_lowest_price_cashiers_still_bargain_only_down_to_the_buying_price(businesses):
    a, _ = businesses
    Membership.objects.filter(user=a['user']).update(role='CASHIER')
    sell = lambda price: a['client'].post('/api/v1/commerce/pos/complete/', {'items': [{'variant_id': a['variant'].pk, 'quantity': 1, 'unit_price': price}]}, format='json')
    assert sell('95').status_code == 201
    assert sell('39').status_code == 400  # the stock cost 40
    assert sell('101').status_code == 403  # above the asking price needs a manager


def test_lowest_price_cannot_exceed_selling_price(businesses):
    a, _ = businesses
    response = a['client'].patch(f"/api/v1/catalog/variants/{a['variant'].pk}/", {'minimum_price': '150'}, format='json')
    assert response.status_code == 400 and 'higher than the selling price' in str(response.json())
    assert a['client'].patch(f"/api/v1/catalog/variants/{a['variant'].pk}/", {'minimum_price': '90'}, format='json').status_code == 200

def test_disabled_services_cannot_be_sold_through_pos(operations):
    a, _ = operations
    Organization.objects.filter(pk=a['org'].pk).update(enabled_modules=['pos'])
    response = a['client'].post('/api/v1/commerce/pos/complete/', {'items': [{'variant_id': a['service'].variant_id, 'quantity': 1}]}, format='json')
    assert response.status_code == 400


@pytest.mark.parametrize('path', ['catalog/products/', 'inventory/receipts/', 'inventory/dashboard/', 'locations/shelves/', 'cyber/services/', 'cyber/jobs/', 'mpesa/transactions/', 'accounting/expenses/', 'accounting/export/', 'accounting/administration/users/', 'store/search-suggestions/?q=private'])
def test_business_endpoints_are_never_public(businesses, path):
    response = APIClient().get('/api/v1/' + path)
    assert response.status_code == 403
    assert 'Alpha' not in response.content.decode() and 'Beta' not in response.content.decode()


def test_private_media_is_tenant_scoped(businesses, tmp_path, settings):
    from django.core.files.base import ContentFile
    from apps.catalog.models import ProductImage
    settings.MEDIA_ROOT = tmp_path
    a, b = businesses
    with organization_context(b['org']):
        picture = ProductImage.objects.create(product=b['product'])
        picture.file.save('private.txt', ContentFile(b'Private business image'))
    path = '/media/' + picture.file.name
    assert APIClient().get(path).status_code == 404
    assert a['client'].get(path).status_code == 404
    response = b['client'].get(path)
    assert response.status_code == 200
    assert response['Cache-Control'] == 'private, no-store'
    response.close()


def test_every_domain_model_has_required_scoped_ownership_and_database_guard():
    from django.apps import apps
    from apps.tenancy.base import TenantModel, TenantManager
    domains = {'core', 'accounts', 'catalog', 'inventory', 'commerce', 'cyber', 'mpesa', 'accounting'}
    for model in apps.get_models():
        if model._meta.label in {'accounts.DeviceSession', 'accounts.RefreshCredential', 'accounts.SessionAudit', 'accounts.AccountProfile', 'accounts.ProtectedPagesPassword'}:
            continue  # Global account security, like auth.User; never business data.
        if model._meta.app_label not in domains:
            continue
        assert issubclass(model, TenantModel), model._meta.label
        assert not model._meta.get_field('organization').null
        assert isinstance(model._default_manager, TenantManager)
        assert isinstance(model._base_manager, TenantManager)
        with connection.cursor() as cursor:
            cursor.execute("SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname='tenant_relationships'", [model._meta.db_table])
            assert cursor.fetchone() == ('O',), model._meta.label


@pytest.mark.parametrize('path,payload', [
    ('catalog/products/', {'name': 'Wrong category', 'slug': 'wrong', 'ecommerce_visible': False}),
    ('locations/zones/', {'name': 'Wrong branch', 'code': 'WRONG'}),
])
def test_create_rejects_foreign_business_relationships(businesses, path, payload):
    a, b = businesses
    if path.startswith('catalog'):
        payload = {**payload, 'category': b['category'].pk}
    else:
        payload = {**payload, 'store': b['store'].pk}
    response = a['client'].post('/api/v1/' + path, payload, format='json')
    # The zone endpoint owns branch selection itself and must ignore browser store IDs.
    if path.startswith('locations') and response.status_code == 201:
        with organization_context(a['org']):
            assert Zone.objects.get(pk=response.json()['id']).store_id == a['store'].pk
    else:
        assert response.status_code == 400, response.content


@pytest.mark.parametrize('path', ['cyber/jobs/{job}/complete/', 'cyber/jobs/{job}/transition/', 'mpesa/sessions/{session}/reconcile/'])
def test_nested_operating_actions_reject_other_business(operations, path):
    a, b = operations
    response = a['client'].post('/api/v1/' + path.format(job=b['job'].pk, session=b['session'].pk), {}, format='json')
    assert response.status_code in {400, 404}, response.content


def test_registration_requires_csrf():
    from django.core.cache import cache
    cache.clear()
    client = APIClient(enforce_csrf_checks=True)
    payload = {'first_name':'Wanjiru','last_name':'Kamau','phone':'0712 345 678','password_confirm':'New-strong-pass-2935','username': 'csrf-owner', 'email': 'csrf@example.test', 'password': 'New-strong-pass-2935'}
    assert client.post('/api/v1/tenancy/register/', payload, format='json').status_code == 403
    csrf = client.get('/api/v1/auth/csrf/').json()['csrfToken']
    assert client.post('/api/v1/tenancy/register/', payload, format='json', HTTP_X_CSRFTOKEN=csrf).status_code == 201


def test_an_ended_subscription_pauses_changes_but_keeps_sales_and_stock(businesses):
    from django.utils import timezone
    a, _ = businesses
    OrganizationSubscription.objects.filter(organization=a['org']).update(ends_at=timezone.now()-timezone.timedelta(seconds=1))
    assert a['client'].get('/api/v1/catalog/products/').status_code == 200
    assert a['client'].post('/api/v1/catalog/categories/', {'name': 'New'}, format='json').status_code == 403
    assert a['client'].post('/api/v1/commerce/pos/complete/', {}, format='json').status_code == 400  # sales stay open; this one is empty
    with organization_context(a['org']):
        assert StockBalance.objects.get(lot=a['lot']).quantity == 5


def test_request_context_is_cleared_after_business_response(businesses):
    from apps.tenancy.context import organization_id
    a, _ = businesses
    assert a['client'].get('/api/v1/catalog/categories/').status_code == 200
    assert organization_id() is None
    assert Category.objects.count() == 0


@pytest.mark.parametrize('path', ['auth/login/', 'auth/password/reset/'])
def test_anonymous_authentication_posts_require_csrf(path):
    from django.core.cache import cache
    cache.clear()
    client = APIClient(enforce_csrf_checks=True)
    assert client.post('/api/v1/' + path, {}, format='json').status_code == 403


def test_inventory_staff_dashboard_does_not_disclose_financial_activity(businesses):
    a, _ = businesses
    Membership.objects.filter(user=a['user']).update(role='INVENTORY')
    data = a['client'].get('/api/v1/inventory/dashboard/').json()
    assert data['today']['revenue'] is None and data['today']['restricted']
    assert data['cyber']['revenue'] is None and data['mpesa']['commission'] is None
    assert data['inventory']['total_skus'] == 1


@pytest.mark.django_db(transaction=True)
def test_read_only_deployment_audit(businesses):
    from io import StringIO
    from django.core.management import call_command
    output = StringIO()
    call_command('audit_tenancy', stdout=output)
    assert 'No ownership gaps found.' in output.getvalue()


def test_evaluated_queryset_cache_cannot_survive_business_switch(businesses):
    a, b = businesses
    rows = Category.objects.order_by('pk')
    with organization_context(a['org']):
        assert [row.pk for row in rows] == [a['category'].pk]
    with organization_context(b['org']):
        assert rows[0].pk == b['category'].pk
        assert not rows.contains(a['category'])
        assert rows.count() == 1
        assert [row.pk for row in rows] == [b['category'].pk]
    assert rows.count() == 0 and not rows.exists() and list(rows) == []


def test_catalog_does_not_bypass_cost_permission(businesses):
    a, _ = businesses
    Membership.objects.filter(user=a['user']).update(role='CASHIER')
    response = a['client'].get(f"/api/v1/catalog/variants/{a['variant'].pk}/")
    assert response.status_code == 200
    assert not {'latest_bp', 'average_stock_cost', 'service_cost'} & response.json().keys()
    response = a['client'].get(f"/api/v1/catalog/products/{a['product'].pk}/")
    assert response.status_code == 200
    assert not {'latest_bp', 'average_stock_cost', 'service_cost'} & response.json()['variants'][0].keys()


def test_dashboard_live_totals_are_isolated_and_follow_enabled_operations(businesses):
    a, b = businesses
    with organization_context(b['org']):
        complete_sale(lines=[{'variant': b['variant'], 'quantity': 3}], channel='POS', number='B-DASH', user=b['user'])
    first = a['client'].get('/api/v1/inventory/dashboard/').json()
    assert first['organization']['name'] == 'Alpha'
    assert Decimal(str(first['today']['revenue'])) == 0
    assert Decimal(str(first['inventory']['physical'])) == 5
    with organization_context(a['org']):
        complete_sale(lines=[{'variant': a['variant'], 'quantity': 2}], channel='POS', number='A-DASH', user=a['user'])
    response = a['client'].get('/api/v1/inventory/dashboard/')
    data = response.json()
    assert response['Cache-Control'] == 'private, no-store'
    assert Decimal(str(data['today']['revenue'])) == 200
    assert Decimal(str(data['today']['profit'])) == 120
    assert Decimal(str(data['inventory']['physical'])) == 3
    assert Decimal(str(data['financial_trend'][-1]['sales'])) == 200
    assert len(data['financial_trend']) == 12
    a['org'].enabled_modules = ['services']
    a['org'].save(update_fields=['enabled_modules'])
    services = a['client'].get('/api/v1/inventory/dashboard/').json()
    assert [unit['key'] for unit in services['business_units'] if unit['enabled']] == ['CYBER']
    assert services['inventory']['restricted']
    assert Decimal(str(services['today']['revenue'])) == 0


def test_dashboard_purchase_cost_expenses_and_unsold_stock_are_distinct(businesses):
    from apps.accounting.models import ExpenseCategory
    from apps.accounting.services import record_expense, reverse
    from apps.inventory.services import create_product_with_opening_stock
    a, b = businesses
    with organization_context(a['org']):
        create_product_with_opening_stock(
            user=a['user'], product_data={'name': 'Opening item', 'category': a['category']},
            variant_data={'sku': 'OPENING', 'selling_price': 100}, preferred_shelf=a['shelf'],
            opening_quantity=3, opening_unit_cost=60)
        complete_sale(lines=[{'variant': a['variant'], 'quantity': 2}], channel='POS', number='PROFIT-SALE', user=a['user'])
        category = ExpenseCategory.objects.create(name='Rent')
        record_expense(user=a['user'], category=category, unit='SHOP', method='CASH', amount=50, description='Rent', key='rent')
        correction = record_expense(user=a['user'], category=category, unit='SHOP', method='CASH', amount=20, description='Duplicate rent', key='duplicate')
        reverse(entry=correction.entry, user=a['user'], reason='Duplicate')
        a['variant'].selling_price = 999
        a['variant'].save(update_fields=['selling_price'])
    with organization_context(b['org']):
        category = ExpenseCategory.objects.create(name='Private expense')
        record_expense(user=b['user'], category=category, unit='SHOP', method='CASH', amount=999, description='Other tenant', key='other')
    response = a['client'].get('/api/v1/inventory/dashboard/')
    assert response.status_code == 200, response.content
    data = response.json()
    period = data['period_summary']
    for field, expected in {'purchases': 200, 'opening_stock': 180, 'revenue': 200, 'cogs': 80,
                            'gross_profit': 120, 'expenses': 50, 'profit': 70}.items():
        assert Decimal(str(period[field])) == expected, field
    assert Decimal(str(data['inventory']['cost'])) == 300
    assert Decimal(str(data['financial_trend'][-1]['purchases'])) == 200
    assert len(data['expense_breakdown']) == 1
    assert data['expense_breakdown'][0]['category'] == 'Rent'
    assert Decimal(str(data['expense_breakdown'][0]['amount'])) == 50
    assert a['client'].get('/api/v1/inventory/dashboard/?start=bad').status_code == 400
    assert a['client'].get('/api/v1/inventory/dashboard/?start=2020-02-01&end=2020-01-01').status_code == 400
    empty = a['client'].get('/api/v1/inventory/dashboard/?start=2020-01-01&end=2020-01-01').json()
    assert Decimal(str(empty['period_summary']['profit'])) == 0
    assert empty['expense_breakdown'] == []


def test_dashboard_debt_collections_payables_and_reversals(businesses):
    from django.utils import timezone
    from apps.accounting.models import CashEntry, PurchasePayment
    from apps.accounting.services import link_receipt, post, reverse
    from apps.inventory.models import StockReceipt, StockReceiptLine
    a, b = businesses
    with organization_context(a['org']):
        sale = complete_sale(lines=[{'variant': a['variant'], 'quantity': 2}], channel='POS',
                             number='CREDIT-1', user=a['user'], payment_status='PENDING')
        payment = sale.payments.get()
        payment.amount = 50
        payment.status = 'COMPLETED'
        payment.save()
        receipt = StockReceipt.objects.create(receipt_number='SUPPLIER-1', received_at=timezone.now(), supplier_name='Local Supplier', created_by=a['user'])
        StockReceiptLine.objects.create(receipt=receipt, variant=a['variant'], received_quantity=5, unit_cost=40, lot=a['lot'])
        purchase = link_receipt(receipt)
        entry = post(unit='SHOP', method='CASH', amount=-60, kind='PURCHASE', reference=receipt.receipt_number, key='supplier-settlement', user=a['user'])
        PurchasePayment.objects.create(purchase=purchase, entry=entry, created_by=a['user'])
    with organization_context(b['org']):
        complete_sale(lines=[{'variant': b['variant'], 'quantity': 1}], channel='POS', number='PRIVATE', user=b['user'], payment_status='PENDING')
    response = a['client'].get('/api/v1/inventory/dashboard/')
    assert response.status_code == 200, response.content
    data = response.json()
    assert Decimal(str(data['receivables']['outstanding'])) == 150
    assert data['receivables']['count'] == 1
    assert Decimal(str(data['collections']['rate'])) == 25
    assert Decimal(str(data['collections']['collected_on_period_sales'])) == 50
    assert Decimal(str(data['payables']['outstanding'])) == 140
    assert data['payables']['rows'][0]['supplier'] == 'Local Supplier'
    assert Decimal(str(data['period_summary']['purchases'])) == 200  # Receipt and lot counted once.
    assert Decimal(str(data['top_items'][0]['quantity'])) == 2
    assert Decimal(str(data['top_items'][0]['sales'])) == 200
    # Accrual: the 200 sale is revenue when sold; only 50 of it has been received so far.
    assert sum(Decimal(str(row['revenue'])) for row in data['performance']['points']) == 200
    assert Decimal(str(data['period_summary']['money_received'])) == 50
    assert data['comparison']['metrics']['revenue']['percent'] is None
    assert Decimal(str(data['account_balances'][0]['balance'])) == -10
    with organization_context(a['org']):
        reverse(entry=CashEntry.objects.get(source_key=f'payment:{payment.pk}'), user=a['user'], reason='Payment correction')
        reverse(entry=entry, user=a['user'], reason='Settlement correction')
    corrected = a['client'].get('/api/v1/inventory/dashboard/').json()
    assert Decimal(str(corrected['receivables']['outstanding'])) == 200
    assert Decimal(str(corrected['collections']['rate'])) == 0
    assert Decimal(str(corrected['payables']['outstanding'])) == 200
    Membership.objects.filter(user=a['user'], organization=a['org']).update(role='INVENTORY')
    restricted = a['client'].get('/api/v1/inventory/dashboard/').json()
    assert restricted['receivables']['restricted']
    assert restricted['payables']['restricted']
    assert restricted['collections']['restricted']
    assert restricted['top_items'] == []
    assert restricted['account_balances'] is None
    assert restricted['recent_entries'] is None
    assert all(row['revenue'] is None for row in restricted['performance']['points'])


def test_selected_branch_resolves_inside_business_context(businesses):
    business = businesses[0]
    response = business['client'].get('/api/v1/tenancy/branches/')
    assert response.status_code == 200
    assert response.json()[0]['is_active'] is True
    assert business['client'].session['branch_id'] == business['store'].pk


def test_suspended_last_branch_assignment_does_not_grant_all_branches(businesses):
    from apps.tenancy.models import BranchMembership
    business = businesses[0]
    Membership.objects.filter(user=business['user']).update(role='CASHIER')
    with organization_context(business['org']):
        other = Store.objects.create(name='Other branch')
        assignment = BranchMembership.objects.create(user=business['user'], store=business['store'])
    client = business['client']
    assert [row['id'] for row in client.get('/api/v1/tenancy/branches/').json()] == [business['store'].pk]
    BranchMembership.objects.filter(pk=assignment.pk).update(status='SUSPENDED')
    assert client.get('/api/v1/tenancy/branches/').json() == []
    identity = client.get('/api/v1/auth/me/').json()
    assert identity['branches'] == []
    assert identity['branch'] is None
    assert 'branch_id' not in client.session
    denied = client.get('/api/v1/catalog/variants/')
    assert denied.status_code == 403
    assert denied.json()['code'] == 'branch_required'
    for store in [business['store'], other, businesses[1]['store']]:
        response = client.post('/api/v1/tenancy/select-branch/', {'branch_id': store.pk}, format='json')
        assert response.status_code == 403


def test_staff_branch_switch_uses_only_active_assignments(businesses):
    from apps.tenancy.models import BranchMembership
    business = businesses[0]
    Membership.objects.filter(user=business['user']).update(role='CASHIER')
    with organization_context(business['org']):
        allowed = Store.objects.create(name='Assigned branch')
        BranchMembership.objects.create(user=business['user'], store=allowed)
    client = business['client']
    response = client.post('/api/v1/tenancy/select-branch/', {'branch_id': allowed.pk}, format='json')
    assert response.status_code == 200
    assert response.json()['is_active'] is True
    identity = client.get('/api/v1/auth/me/').json()
    assert identity['branch']['id'] == allowed.pk
    assert [row['id'] for row in identity['branches']] == [allowed.pk]
    response = client.post('/api/v1/tenancy/select-branch/', {'branch_id': business['store'].pk}, format='json')
    assert response.status_code == 403
    assert client.session['branch_id'] == allowed.pk


def test_a_sale_recorded_at_the_full_price_is_corrected_to_what_was_really_paid(businesses):
    """Sold for 70 after bargaining but recorded at 100 cash: reverse the payment, credit 30, record the 70 received."""
    from apps.accounting import statements
    from apps.commerce.models import Payment, Sale
    from apps.commerce.returns import sale_balance
    a, _ = businesses
    client = a['client']
    made = client.post('/api/v1/commerce/pos/complete/', {'items': [{'variant_id': a['variant'].pk, 'quantity': 1}]}, format='json')
    assert made.status_code == 201, made.content
    sale_id = made.json()['sale_id']
    with organization_context(a['org']):
        payment = Payment.objects.get(sale_id=sale_id)
    assert client.post(f'/api/v1/commerce/payments/{payment.pk}/reverse/', {'reason': ''}, format='json').status_code == 400
    undone = client.post(f'/api/v1/commerce/payments/{payment.pk}/reverse/', {'reason': 'Only 70 was received'}, format='json')
    assert undone.status_code == 200 and undone.json()['status'] == 'REVERSED'
    assert client.post(f'/api/v1/commerce/sales/{sale_id}/notes/', {'kind': 'CREDIT', 'amount': '30', 'reason': 'Customer bargained to 70',
                       'idempotency_key': 'note-1'}, format='json').status_code == 201
    assert client.post(f'/api/v1/commerce/sales/{sale_id}/payments/', {'amount': '70', 'method': 'CASH', 'idempotency_key': 'pay-70'},
                       format='json').status_code == 201
    listed = next(row for row in client.get('/api/v1/commerce/sales/').json()['results'] if row['id'] == sale_id)
    assert (Decimal(str(listed['total'])), Decimal(str(listed['charged'])), listed['created_at'] is not None) == (Decimal('100.00'), Decimal('70.00'), True)
    with organization_context(a['org']), branch_context(a['store'].pk):
        sale = Sale.objects.get(pk=sale_id)
        assert sale_balance(sale) == 0
        books = statements.balances()
        assert -books['4000']['balance'] == Decimal('70.00') and books['1000']['balance'] == Decimal('70.00')
        assert books['1100']['balance'] == 0
