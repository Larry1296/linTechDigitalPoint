"""Receiving stock through the API must book the purchase without extra clerical work.

Two independent businesses (an electronics shop and a grocery kiosk) each receive
several items. Every receipt must produce one supplier purchase, a balanced
Stock / Supplier-balances journal, a payable that shrinks as the supplier is paid,
and nothing visible to the other business.
"""
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from apps.accounting.models import JournalEntry, Supplier, SupplierPurchase
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db

SHOPS = {
    'lintech': {
        'name': 'linTech Digital Point',
        'items': [('Tecno Camon 22 cover', 20, '120'), ('Type-C fast charger', 10, '350'), ('Wired earphones', 15, '200')],
        'supplier': 'Phone Accessories Ltd',
    },
    'mama-mboga': {
        'name': 'Mama Mboga Kiandas',
        'items': [('Sukuma wiki (bunch)', 50, '10'), ('Tomatoes (kg)', 30, '80'), ('Onions (kg)', 20, '90')],
        'supplier': 'Wakulima Market',
    },
}


def open_business(slug, spec):
    user = User.objects.create_user(f'owner-{slug}', password='Safe-pass-1848', is_staff=True)
    org = Organization.objects.create(name=spec['name'], slug=slug, owner=user)
    Membership.objects.create(user=user, organization=org, role='OWNER')
    OrganizationSubscription.objects.create(organization=org, status='ACTIVE')
    with organization_context(org):
        store = Store.objects.create(name=spec['name'])
        category = Category.objects.create(name='Stock', slug='stock')
        variants = []
        for index, (name, _, _) in enumerate(spec['items']):
            product = Product.objects.create(name=name, slug=f'item-{index}', category=category)
            variants.append(ProductVariant.objects.create(product=product, sku=f'SKU-{index}', selling_price=1000))
    client = APIClient()
    client.force_login(user)
    return dict(user=user, org=org, store=store, variants=variants, client=client, spec=spec)


def receive(business, reference, items):
    lines = [{'variant_id': variant.pk, 'received_quantity': str(qty), 'unit_cost': cost}
             for variant, (_, qty, cost) in zip(business['variants'], items)]
    response = business['client'].post('/api/v1/inventory/receipts/', {
        'supplier_name': business['spec']['supplier'], 'external_reference': reference, 'lines': lines,
    }, format='json')
    assert response.status_code == 201, response.content
    return response.json()


def ledger(business):
    response = business['client'].get(f"/api/v1/accounting/ledger/reports/?branch={business['store'].pk}")
    assert response.status_code == 200, response.content
    data = response.json()
    return data, {row['account__code']: Decimal(str(row['debit'])) - Decimal(str(row['credit'])) for row in data['trial_balance']}


def test_several_received_items_are_booked_as_purchases_per_business():
    shops = {slug: open_business(slug, spec) for slug, spec in SHOPS.items()}

    # Each business receives its three items, then a second, smaller delivery of the first item.
    for slug, shop in shops.items():
        receive(shop, f'{slug.upper()}-INV-001', shop['spec']['items'])
        name, _, cost = shop['spec']['items'][0]
        receive(shop, f'{slug.upper()}-INV-002', [(name, 5, cost)])

    expected = {'lintech': (Decimal(8900), Decimal(600)), 'mama-mboga': (Decimal(4700), Decimal(50))}
    for slug, shop in shops.items():
        first_total, second_total = expected[slug]
        with organization_context(shop['org']):
            purchases = list(SupplierPurchase.objects.order_by('pk'))
            assert [p.amount for p in purchases] == [first_total, second_total]
            assert {p.supplier.name for p in purchases} == {shop['spec']['supplier']}
            assert Supplier.objects.count() == 1
            assert JournalEntry.objects.filter(source_key__startswith='purchase:').count() == 2

        data, balance = ledger(shop)
        stock_value = first_total + second_total
        assert balance['1200'] == stock_value           # Stock asset (debit)
        assert balance['2000'] == -stock_value          # Owed to supplier (credit)
        assert Decimal(str(data['debits'])) == Decimal(str(data['credits']))
        assert Decimal(str(data['balance_sheet']['difference'])) == 0
        assert Decimal(str(data['profit_loss']['net_profit'])) == 0  # Buying stock is not an expense.

    # Paying part of the first linTech invoice in M-Pesa reduces the payable and mobile money.
    lintech = shops['lintech']
    with organization_context(lintech['org']):
        invoice = SupplierPurchase.objects.get(receipt__receipt_number='LINTECH-INV-001')
    pay = lambda amount, key: lintech['client'].post(f'/api/v1/accounting/purchases/{invoice.pk}/pay/',
        {'amount': amount, 'payment_method': 'MPESA', 'idempotency_key': key}, format='json')
    assert pay('5000.00', 'pay-1').status_code == 201
    assert pay('5000.00', 'pay-1').status_code == 200            # Retried request is not double-paid.
    assert pay('3900.01', 'pay-2').status_code == 400            # Cannot pay more than is owed.
    _, balance = ledger(lintech)
    assert balance['2000'] == -Decimal(4500)
    assert balance['1020'] == -Decimal(5000)                     # No opening cash was recorded.

    # Neither business can see the other's purchases.
    for slug, shop in shops.items():
        rows = shop['client'].get('/api/v1/accounting/purchases/').json()
        rows = rows.get('results', rows) if isinstance(rows, dict) else rows
        with organization_context(shop['org']):
            own = set(SupplierPurchase.objects.values_list('pk', flat=True))
        assert {row['id'] for row in rows} == own and len(own) == 2
        assert {row['organization'] for row in rows} == {shop['org'].pk}
    _, grocer = ledger(shops['mama-mboga'])
    assert '1020' not in grocer and grocer['1200'] == Decimal(4750)
