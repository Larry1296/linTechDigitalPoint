from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from apps.catalog.models import Category, Product, ProductVariant
from apps.commerce.models import Payment, Sale
from apps.core.models import Store
from apps.cyber.models import CyberServiceProfile, ServiceMaterialRequirement
from apps.cyber.services import complete_job, create_job
from apps.inventory.models import Movement, Shelf, StockBalance, Zone
from apps.inventory.services import receive_stock
from apps.mpesa.models import MpesaTransaction


@pytest.fixture
def cyber_data(db):
    owner = User.objects.create_superuser("cyber-owner", "owner@example.test", "test")
    category = Category.objects.create(name="Cyber", slug="cyber")
    variants = {}
    for name, price, unit in [("B&W Print", 10, "PER_PAGE"), ("Scanning", 20, "PER_PAGE"), ("Binding", 100, "PER_DOCUMENT")]:
        product = Product.objects.create(name=name, slug=name.lower().replace("&", "and").replace(" ", "-"), category=category, product_type="SERVICE")
        variant = ProductVariant.objects.create(product=product, sku=f"CYB-{len(variants)}", selling_price=price, service_cost=2)
        CyberServiceProfile.objects.create(variant=variant, billing_unit=unit)
        variants[name] = variant
    return owner, variants


@pytest.mark.django_db
def test_cyber_job_totals_and_mpesa_sale_payment_are_distinct(cyber_data):
    owner, variants = cyber_data
    job = create_job(user=owner, lines=[{"variant_id": variants["B&W Print"].id, "quantity": 10}, {"variant_id": variants["Scanning"].id, "quantity": 5}, {"variant_id": variants["Binding"].id, "quantity": 1}])
    assert job.total == Decimal("300.00")
    sale = complete_job(job=job, user=owner, payment_method="MPESA", payment_reference="SALE-PAYMENT")
    job.refresh_from_db()
    assert job.status == "COMPLETED" and job.sale == sale
    assert sale.channel == Sale.CYBER and sale.total == Decimal("300.00")
    assert Payment.objects.get(sale=sale).method == "MPESA"
    assert not MpesaTransaction.objects.exists()
    assert complete_job(job=job, user=owner, payment_method="CASH") == sale
    assert Sale.objects.filter(cyber_job=job).count() == 1


@pytest.mark.django_db
def test_cyber_material_consumes_fifo_inventory_without_double_counting_service_cost(cyber_data):
    owner, variants = cyber_data
    category = Category.objects.create(name="Consumables", slug="consumables")
    paper_product = Product.objects.create(name="A4 Paper Sheet", slug="a4-paper-sheet", category=category)
    paper = ProductVariant.objects.create(product=paper_product, sku="A4-SHEET", selling_price=1)
    store = Store.objects.create(name="LinTech")
    zone = Zone.objects.create(store=store, code="STORE", name="Store")
    shelf = Shelf.objects.create(zone=zone, code="PAPER-1", display_name="Paper", x=0, y=0, width=1, height=1, created_by=owner)
    receive_stock(variant=paper, placements=[{"shelf": shelf, "quantity": 500}], unit_cost="0.50", reference="PAPER-OPEN", user=owner)
    ServiceMaterialRequirement.objects.create(service_variant=variants["B&W Print"], material_variant=paper, quantity_per_service_unit=1)
    job = create_job(user=owner, lines=[{"variant_id": variants["B&W Print"].id, "quantity": 20}])
    sale = complete_job(job=job, user=owner, payment_method="CASH")
    assert StockBalance.objects.get(lot__variant=paper).quantity == 480
    assert sale.cogs == Decimal("10.00")
    assert Movement.objects.get(movement_type="CYBER_CONSUMPTION").quantity == 20
