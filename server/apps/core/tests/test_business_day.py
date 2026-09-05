from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product, ProductVariant
from apps.commerce.models import Sale
from apps.core.models import Store
from apps.cyber.models import CyberServiceProfile
from apps.cyber.services import complete_job, create_job
from apps.inventory.models import Shelf, Zone
from apps.inventory.services import complete_sale, receive_stock
from apps.mpesa.models import MpesaCommissionEntry, MpesaOutlet
from apps.mpesa.services import open_session, post_transaction, record_commission, session_balances


@pytest.mark.django_db
def test_full_business_day_keeps_retail_cyber_and_mpesa_principal_distinct():
    owner = User.objects.create_superuser("business-owner", "owner@example.test", "test")
    store = Store.objects.create(name="LinTech Digital Point")
    category = Category.objects.create(name="Business Day", slug="business-day")
    zone = Zone.objects.create(store=store, code="SHOP", name="Shop")
    shelf = Shelf.objects.create(zone=zone, code="SHOP-01", display_name="Shop", x=0, y=0, width=1, height=1, created_by=owner)

    charger_product = Product.objects.create(name="Phone charger", slug="day-phone-charger", category=category)
    charger = ProductVariant.objects.create(product=charger_product, sku="DAY-CHARGER", selling_price=1000)
    receive_stock(variant=charger, placements=[{"shelf": shelf, "quantity": 1}], unit_cost=600, reference="DAY-STOCK", user=owner)
    retail_sale = complete_sale(lines=[{"variant": charger, "quantity": 1}], channel=Sale.POS, number="DAY-RETAIL", user=owner)

    cyber_lines = []
    for name, price, quantity, unit in [("B&W prints", 10, 20, "PER_PAGE"), ("Scans", 20, 5, "PER_PAGE"), ("Binding", 150, 1, "PER_DOCUMENT")]:
        product = Product.objects.create(name=name, slug=f"day-{name.lower().replace('&', 'and').replace(' ', '-')}", category=category, product_type="SERVICE")
        variant = ProductVariant.objects.create(product=product, sku=f"DAY-CYB-{len(cyber_lines)}", selling_price=price)
        CyberServiceProfile.objects.create(variant=variant, billing_unit=unit)
        cyber_lines.append({"variant_id": variant.id, "quantity": quantity})
    cyber_job = create_job(user=owner, lines=cyber_lines)
    cyber_sale = complete_job(job=cyber_job, user=owner, payment_method="MPESA", payment_reference="CYBER-BILL-PAID")

    outlet = MpesaOutlet.objects.create(store=store, display_name="Main Agent")
    shift = open_session(outlet=outlet, operator=owner, opening_cash=30000, opening_float=40000)
    post_transaction(session=shift, transaction_type="CUSTOMER_DEPOSIT", transaction_amount=10000, user=owner, idempotency_key="day-deposit")
    post_transaction(session=shift, transaction_type="CUSTOMER_WITHDRAWAL", transaction_amount=5000, user=owner, idempotency_key="day-withdrawal")

    assert retail_sale.total == Decimal("1000.00")
    assert cyber_sale.total == Decimal("450.00") and cyber_sale.channel == Sale.CYBER
    assert session_balances(shift) == (Decimal("35000.00"), Decimal("35000.00"))
    assert Sale.objects.aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("total"))["total"] == Decimal("1450.00")

    record_commission(outlet=outlet, user=owner, period=__import__("django.utils.timezone", fromlist=["localdate"]).localdate(), commission_amount=650, reference="DAY-COMMISSION", settlement_method="FLOAT")
    assert MpesaCommissionEntry.objects.get().amount == Decimal("650.00")
    client = APIClient()
    client.force_authenticate(owner)
    dashboard = client.get("/api/v1/inventory/dashboard/").json()
    assert Decimal(str(dashboard["today"]["revenue"])) == Decimal("2100.00")
    assert dashboard["mpesa"]["principal_revenue"] == 0
    assert Decimal(str(dashboard["mpesa"]["deposits"])) == Decimal("10000.00")
    assert Decimal(str(dashboard["mpesa"]["withdrawals"])) == Decimal("5000.00")
