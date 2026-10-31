"""Accrual accounting against real database records (see docs/accounting-policy.md).

Every profit figure here is asserted to the cent and traced to its cost layers and journals.
"""
from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.accounting import statements
from apps.accounting.models import ExpenseCategory, JournalEntry
from apps.accounting.services import cancel_expense, pay_expense, record_expense
from apps.catalog.models import Category, Product, ProductVariant
from apps.commerce.models import Sale, SaleAllocation
from apps.commerce.returns import adjust_sale_price, return_items, sale_balance
from apps.commerce.settlements import collect
from apps.core.models import AuditLog, Store
from apps.inventory.models import StockLot
from apps.inventory.purchase_returns import correct_lot_cost, return_to_supplier
from apps.inventory.services import complete_sale, complete_stock_receipt

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def shop():
    owner = User.objects.create_superuser("owner", "owner@example.test", "Owner-pass-2026")
    Store.objects.create(name="Main branch")
    category = Category.objects.create(name="Networking", slug="networking")
    router = ProductVariant.objects.create(product=Product.objects.create(name="Wi-Fi router", slug="router", category=category),
                                           name="AC1200", sku="RTR-1", selling_price=1000)
    return {"owner": owner, "router": router, "category": category, "count": [0]}


def receive(shop, quantity, cost, days_ago=0, **extra):
    shop["count"][0] += 1
    return complete_stock_receipt(supplier_name=extra.pop("supplier", "Tech Supplies"), external_reference=f"INV-{shop['count'][0]}",
                                  received_at=timezone.now() - timedelta(days=days_ago, minutes=shop["count"][0]),
                                  lines=extra.pop("lines", None) or [{"variant_id": shop["router"].pk, "received_quantity": str(quantity), "unit_cost": str(cost)}],
                                  user=extra.pop("user", shop["owner"]), **extra)


def sell(shop, quantity, price=None, user=None, number=None, **extra):
    shop["count"][0] += 1
    line = {"variant": shop["router"], "quantity": quantity}
    if price is not None:
        line["unit_price"] = D(price)
    line.update(extra.pop("line", {}))
    return complete_sale(lines=[line], channel="POS", number=number or f"S-{shop['count'][0]}", user=user or shop["owner"], **extra)


def balance(code):
    return statements.balances().get(code, {}).get("balance", D(0))


def assert_every_journal_balances():
    for entry in JournalEntry.objects.all():
        totals = entry.lines.aggregate(d=Sum("debit"), c=Sum("credit"))
        assert totals["d"] == totals["c"], entry.source_key


def layers():
    return [(lot.remaining_quantity, lot.unit_cost) for lot in StockLot.objects.order_by("received_at", "pk")]


def test_three_fifo_layers_one_sale_consumes_two_and_later_costs_are_kept(shop):
    receive(shop, 10, 500, days_ago=3)
    receive(shop, 10, 550, days_ago=2)
    receive(shop, 10, 600, days_ago=1)
    sale = sell(shop, 12, price=900)
    item = sale.items.get()
    assert [(a.quantity, a.unit_cost) for a in item.allocations.order_by("lot__received_at")] == [(D("10.000"), D("500.0000")), (D("2.000"), D("550.0000"))]
    assert item.cost == D("6100.00") and sale.cogs == D("6100.00")
    assert sale.net_total == D("10800.00") and sale.gross_profit == D("4700.00")
    assert layers() == [(D("0.000"), D("500.0000")), (D("8.000"), D("550.0000")), (D("10.000"), D("600.0000"))]
    assert balance("1200") == D("10400.00")  # 8 × 550 + 10 × 600, each layer at its own cost
    assert_every_journal_balances()


def test_bought_at_500_then_550_sold_at_800_and_700_with_catalogue_and_loss_sales(shop):
    receive(shop, 2, 500, days_ago=3)
    receive(shop, 2, 550, days_ago=2)
    first = sell(shop, 1, price=800)
    line = first.items.get()
    assert (line.list_price, line.unit_price, line.net_amount, line.cost) == (D("1000.00"), D("800.00"), D("800.00"), D("500.00"))
    assert first.gross_profit == D("300.00")
    second = sell(shop, 2, price=700)
    assert (second.net_total, second.cogs, second.gross_profit) == (D("1400.00"), D("1050.00"), D("350.00"))  # 500 + 550
    assert layers() == [(D("0.000"), D("500.0000")), (D("1.000"), D("550.0000"))]

    at_catalogue = sell(shop, 1)
    assert at_catalogue.items.get().unit_price == D("1000.00") and at_catalogue.gross_profit == D("450.00")

    receive(shop, 2, 600, days_ago=1)
    cashier = User.objects.create_user("cashier", password="Cashier-pass-2026", is_staff=True)
    with pytest.raises(ValidationError) as refused:
        sell(shop, 1, price=400, user=cashier, allow_below_cost=True)
    assert "below_cost" in str(refused.value.detail)
    with pytest.raises(ValidationError):
        sell(shop, 1, price=400)  # even the owner must acknowledge the warning
    loss = sell(shop, 1, price=400, allow_below_cost=True)
    assert (loss.net_total, loss.cogs, loss.gross_profit) == (D("400.00"), D("600.00"), D("-200.00"))
    assert AuditLog.objects.filter(action="SALE_BELOW_COST", object_id=str(loss.pk)).exists()
    explained = statements.explain_sale_item(loss.items.get().pk)
    assert explained["line"]["loss"] is True and explained["line"]["gross_profit"] == D("-200.00")

    retail = statements.profit_and_loss(None, None)["units"][0]
    assert (retail["revenue"], retail["direct_costs"], retail["gross_profit"]) == (D("3600.00"), D("2700.00"), D("900.00"))
    assert layers()[-1] == (D("1.000"), D("600.0000"))
    assert_every_journal_balances()


def test_discount_return_to_shelf_and_damaged_return_with_refund(shop):
    receive(shop, 5, 400)
    sale = sell(shop, 3, line={"discount": D("300"), "discount_reason": "Loyal customer"})
    item = sale.items.get()
    assert (item.list_price, item.discount, item.discount_reason, item.net_amount, item.cost) == (
        D("1000.00"), D("300.00"), "Loyal customer", D("2700.00"), D("1200.00"))
    return_items(sale=sale, lines=[{"item_id": item.pk, "quantity": 1, "restock": True}], reason="Wrong model", user=shop["owner"])
    damaged = return_items(sale=sale, lines=[{"item_id": item.pk, "quantity": 1, "restock": False}], reason="Arrived broken",
                           user=shop["owner"], refund={"method": "CASH", "amount": "1800"})
    assert damaged.refund_amount == D("1800.00") and sale_balance(sale) == D("0.00")
    pl = statements.profit_and_loss(None, None)
    assert pl["units"][0]["revenue"] == D("900.00") and pl["units"][0]["direct_costs"] == D("400.00")
    assert pl["operating_expenses"] == [] and pl["stock_corrections"] == D("400.00")  # damaged unit written off once, as a stock loss
    assert StockLot.objects.get().remaining_quantity == D("3.000")  # 5 − 3 sold + 1 restocked
    assert balance("1000") == D("900.00")  # received 2,700 and refunded 1,800
    assert_every_journal_balances()


def test_credit_sale_partial_payment_then_settlement_recognises_revenue_once(shop):
    receive(shop, 2, 300)
    sale = sell(shop, 1, price=1000, paid_amount=0)
    assert statements.profit_and_loss(None, None)["revenue"] == D("1000.00") and balance("1100") == D("1000.00")
    assert statements.explain_sale_item(sale.items.get().pk)["sale"]["payment_status"] == "UNPAID"
    collect(sale=sale, amount=D("400"), method="CASH", key="part-1")
    assert sale_balance(sale) == D("600.00") and statements.explain_sale_item(sale.items.get().pk)["sale"]["payment_status"] == "PARTLY_PAID"
    collect(sale=sale, amount=D("600"), method="CASH", key="part-2")
    collect(sale=sale, amount=D("600"), method="CASH", key="part-2")  # retried request is not paid twice
    assert sale_balance(sale) == 0 and balance("1100") == 0 and balance("1000") == D("1000.00")
    assert statements.profit_and_loss(None, None)["revenue"] == D("1000.00")  # payments never add revenue
    today = timezone.localdate()
    assert statements.owner_summary(today, today)["money_received"]["amount"] == D("1000.00")
    assert_every_journal_balances()


def test_receipts_paid_now_on_credit_with_landed_costs_purchase_return_and_write_off(shop):
    from apps.accounting.models import SupplierPurchase
    from apps.accounting.services import purchase_outstanding
    from apps.inventory.adjustments import adjust_stock
    paid_now = receive(shop, 5, 100, payment={"method": "CASH", "amount": "500"})
    assert purchase_outstanding(SupplierPurchase.objects.get(receipt=paid_now)) == 0
    modem = ProductVariant.objects.create(product=Product.objects.create(name="Modem", slug="modem", category=shop["category"]), sku="MDM", selling_price=500)
    credit = receive(shop, 0, 0, lines=[{"variant_id": shop["router"].pk, "received_quantity": "10", "unit_cost": "200"},
                                         {"variant_id": modem.pk, "received_quantity": "10", "unit_cost": "100"}],
                     landed_costs=[{"description": "Transport", "amount": "150", "paid_by": "CASH"},
                                   {"description": "Handling on invoice", "amount": "90", "paid_by": "SUPPLIER_INVOICE"}])
    lines = list(credit.lines.order_by("pk"))
    assert [(line.unit_cost, line.landed_cost, line.lot.unit_cost) for line in lines] == [
        (D("200.00"), D("160.00"), D("216.0000")), (D("100.00"), D("80.00"), D("108.0000"))]  # 240 split 2,000 : 1,000
    assert "allocated to lines in proportion" in credit.landed_allocation_note
    purchase = SupplierPurchase.objects.get(receipt=credit)
    assert purchase.amount == D("3090.00") and purchase_outstanding(purchase) == D("3090.00")
    returned = return_to_supplier(receipt=credit, lines=[{"line_id": lines[0].pk, "quantity": 2}], reason="Two faulty units", user=shop["owner"])
    assert returned.total_cost == D("432.00") and purchase_outstanding(purchase) == D("2658.00")
    assert balance("2000") == -D("2658.00")
    lot = lines[1].lot
    shelf = lot.balances.get().shelf
    adjust_stock(user=shop["owner"], variant_id=modem.pk, shelf_id=shelf.pk, expected_quantity=D("10"), counted_quantity=D("9"),
                 reason="Damaged item", notes="Crushed in transit", idempotency_key="count-1", confirmed=True)
    assert balance("6100") == D("108.00")  # one modem written off at its layer cost
    assert balance("1200") == D("500.00") + D("8") * D("216") + D("9") * D("108")
    assert balance("1000") == -D("650.00")  # 500 to the supplier + 150 transport
    assert_every_journal_balances()


def test_missing_buying_price_is_blocked_and_uncosted_opening_stock_is_flagged(shop):
    with pytest.raises(ValidationError, match="buying price"):
        receive(shop, 3, 0)
    with pytest.raises(ValidationError, match="opening stock"):
        receive(shop, 3, 0, lines=[{"variant_id": shop["router"].pk, "received_quantity": "3", "unit_cost": "0", "uncosted": True}])
    opening = receive(shop, 0, 0, document_status="OPENING_BALANCE", supplier="",
                      lines=[{"variant_id": shop["router"].pk, "received_quantity": "3", "unit_cost": "0", "uncosted": True}])
    lot = opening.lines.get().lot
    assert lot.cost_status == StockLot.UNCOSTED and balance("1200") == 0
    sale = sell(shop, 1, price=900)
    assert sale.cost_pending and sale.items.get().cost_pending
    today = timezone.localdate()
    warnings = {w["key"]: w for w in statements.warnings_for(today, today)}
    assert warnings["uncosted_sales"]["quantity"] == D("1.000") and warnings["uncosted_sales"]["amount"] == D("900.00")
    assert "uncosted_stock" in warnings
    correction = correct_lot_cost(lot=lot, unit_cost=D("450"), reason="Found the original invoice", user=shop["owner"])
    assert (correction.sold_quantity, correction.inventory_amount, correction.cogs_amount) == (D("1.000"), D("900.00"), D("450.00"))
    assert balance("1200") == D("900.00") and balance("5000") == D("450.00") and balance("3000") == -D("1350.00")
    assert "uncosted_sales" not in {w["key"] for w in statements.warnings_for(today, today)}
    assert_every_journal_balances()


def test_expenses_paid_and_owed_count_once_and_cancellations_reverse(shop):
    rent = ExpenseCategory.objects.create(name="Rent")
    power = ExpenseCategory.objects.create(name="Electricity")
    record_expense(user=shop["owner"], category=rent, unit="SHOP", method="BANK", amount=1000, description="September rent", key="rent")
    bill = record_expense(user=shop["owner"], category=power, unit="SHOP", method="CASH", amount=300, description="KPLC token",
                          key="power", paid=False, due_date=timezone.localdate())
    assert balance("2150") == -D("300.00") and statements.payables()["bills"][0]["owed"] == D("300.00")
    pay_expense(expense=bill, amount=D("300"), method="CASH", key="power-paid", user=shop["owner"])
    pay_expense(expense=bill, amount=D("300"), method="CASH", key="power-paid", user=shop["owner"])  # retried
    duplicate = record_expense(user=shop["owner"], category=rent, unit="SHOP", method="BANK", amount=1000, description="Rent typed twice", key="dup")
    cancel_expense(expense=duplicate, user=shop["owner"], reason="Duplicate")
    pl = statements.profit_and_loss(None, None)
    assert {e["name"]: e["amount"] for e in pl["operating_expenses"]} == {"Rent": D("1000.00"), "Electricity": D("300.00")}
    assert pl["net_profit_before_tax"] == -D("1300.00") and pl["loss"] is True
    assert balance("2150") == 0 and balance("1010") == -D("1000.00") and balance("1000") == -D("300.00")
    assert_every_journal_balances()


def test_cyber_job_consumes_paper_as_its_direct_cost_not_an_expense(shop):
    from apps.cyber.models import CyberServiceProfile, ServiceMaterialRequirement
    from apps.cyber.services import complete_job, create_job
    service_category = Category.objects.create(name="Cyber", slug="cyber")
    printing = ProductVariant.objects.create(product=Product.objects.create(name="B&W print", slug="print", category=service_category, product_type="SERVICE"),
                                             sku="PRINT", selling_price=10, service_cost=2)
    CyberServiceProfile.objects.create(variant=printing, billing_unit="PER_PAGE")
    paper = ProductVariant.objects.create(product=Product.objects.create(name="A4 paper", slug="a4", category=shop["category"]), sku="A4", selling_price=1)
    receive(shop, 0, 0, lines=[{"variant_id": paper.pk, "received_quantity": "500", "unit_cost": "0.50"}])
    ServiceMaterialRequirement.objects.create(service_variant=printing, material_variant=paper, quantity_per_service_unit=1)
    sale = complete_job(job=create_job(user=shop["owner"], lines=[{"variant_id": printing.pk, "quantity": 20}]), user=shop["owner"], payment_method="CASH")
    assert (sale.net_total, sale.cogs, sale.gross_profit) == (D("200.00"), D("10.00"), D("190.00"))
    services = statements.profit_and_loss(None, None)["units"][1]
    assert (services["revenue"], services["direct_costs"]) == (D("200.00"), D("10.00"))  # configured cost 2/page not added
    assert statements.profit_and_loss(None, None)["operating_expenses"] == []
    assert_every_journal_balances()


def test_mpesa_principal_is_not_revenue_and_commission_is(shop):
    from apps.mpesa.models import MpesaOutlet
    from apps.mpesa.services import open_session, post_transaction, record_commission
    outlet = MpesaOutlet.objects.create(store=Store.objects.get(), display_name="Agent till")
    session = open_session(outlet=outlet, operator=shop["owner"], opening_cash="50000", opening_float="50000")
    post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678",transaction_amount=20000, user=shop["owner"], idempotency_key="dep",
                     provider_reference="QWE123RTY")
    record_commission(outlet=outlet, user=shop["owner"], period=timezone.localdate(), commission_amount=D("135"), reference="COMM-SEP",
                      settlement_method="MPESA")
    pl = statements.profit_and_loss(None, None)
    assert pl["revenue"] == D("135.00") and pl["units"][2]["revenue"] == D("135.00")
    rows = {r["key"]: r for r in statements.reconciliation()}
    assert rows["agency_cash"]["reconciled"] and rows["agency_float"]["reconciled"]
    assert_every_journal_balances()


def test_price_correction_notes_and_every_posting_is_idempotent(shop):
    receive(shop, 4, 500, idempotency_key="receipt-key")
    receive(shop, 4, 500, idempotency_key="receipt-key")  # the same delivery is not received twice
    assert StockLot.objects.count() == 1
    sale = sell(shop, 2, price=900, idempotency_key="sale-key", number="SALE-1")
    again = sell(shop, 2, price=900, idempotency_key="sale-key", number="SALE-2")
    assert again.pk == sale.pk and SaleAllocation.objects.count() == 1
    note = adjust_sale_price(sale=sale, kind="CREDIT", amount=D("100"), reason="Price match", user=shop["owner"], idempotency_key="note")
    assert adjust_sale_price(sale=sale, kind="CREDIT", amount=D("100"), reason="Price match", user=shop["owner"], idempotency_key="note").pk == note.pk
    assert sale.items.get().unit_price == D("900.00")  # the posted sale is never edited
    first = return_items(sale=sale, lines=[{"item_id": sale.items.get().pk, "quantity": 1}], reason="Changed mind", user=shop["owner"], idempotency_key="ret")
    assert return_items(sale=sale, lines=[{"item_id": sale.items.get().pk, "quantity": 1}], reason="Changed mind", user=shop["owner"], idempotency_key="ret").pk == first.pk
    # Revenue: 1,800 sold − 100 credit note − 850 for the returned unit: after the note each unit cost the
    # customer 850, so that is what the return credits back (never more than was actually charged).
    assert statements.profit_and_loss(None, None)["revenue"] == D("850.00")
    # Paid 1,800 in full at the sale, so the business now owes the customer 950.
    assert sale_balance(sale) == -D("950.00") and balance("1100") == -D("950.00")
    assert_every_journal_balances()


def test_reports_reconcile_to_inventory_receivables_payables_and_journals(shop):
    receive(shop, 10, 500, days_ago=2)
    receive(shop, 5, 520, days_ago=1)
    sell(shop, 3, price=900, paid_amount=0)
    sell(shop, 2, price=950)
    record_expense(user=shop["owner"], category=ExpenseCategory.objects.create(name="Transport"), unit="SHOP", method="CASH",
                   amount=250, description="Delivery run", key="transport", paid=False)
    rows = statements.reconciliation()
    assert all(row["reconciled"] for row in rows), rows
    trial = statements.trial_balance(None, None)
    assert trial["debits"] == trial["credits"]
    assert statements.balance_sheet(None)["difference"] == 0
    assert sum((r["value"] for r in statements.stock_valuation()), D(0)) == balance("1200") == D("5") * 500 + D("5") * 520
    assert sum((r["owed"] for r in statements.receivables()), D(0)) == balance("1100") == D("2700.00")
    assert_every_journal_balances()


def test_opening_stock_from_the_product_form_is_valued_or_flagged_never_assumed(shop):
    from apps.inventory.services import create_product_with_opening_stock
    _, known = create_product_with_opening_stock(user=shop["owner"], product_data={"name": "HDMI cable", "category": shop["category"]},
                                                 variant_data={"sku": "HDMI", "selling_price": 300}, opening_quantity=10, opening_unit_cost=120)
    _, unknown = create_product_with_opening_stock(user=shop["owner"], product_data={"name": "Old mouse", "category": shop["category"]},
                                                   variant_data={"sku": "MOUSE", "selling_price": 250}, opening_quantity=4, opening_unit_cost=0)
    assert known.lots.get().cost_status == StockLot.COSTED and unknown.lots.get().cost_status == StockLot.UNCOSTED
    assert balance("1200") == D("1200.00") and balance("3000") == -D("1200.00")  # owner's existing stock, at its recorded cost
    today = timezone.localdate()
    assert "uncosted_stock" in {w["key"] for w in statements.warnings_for(today, today)}


def test_a_product_entered_by_mistake_can_be_deleted_and_its_opening_value_is_reversed(shop):
    from rest_framework.exceptions import ValidationError
    from apps.inventory.services import create_product_with_opening_stock, delete_unused_product
    mistake, _ = create_product_with_opening_stock(user=shop["owner"], product_data={"name": "Typo charger", "category": shop["category"]},
                                                   variant_data={"sku": "TYPO", "selling_price": 250}, opening_quantity=4, opening_unit_cost=110)
    assert balance("1200") == D("440.00")
    delete_unused_product(mistake, shop["owner"])
    assert not Product.objects.filter(name="Typo charger").exists() and not StockLot.objects.filter(variant__sku="TYPO").exists()
    assert balance("1200") == D("0.00") and balance("3000") == D("0.00")
    assert_every_journal_balances()
    receive(shop, 2, 500)
    sell(shop, 1)
    with pytest.raises(ValidationError, match="can't be deleted because it has been sold"):
        delete_unused_product(shop["router"].product, shop["owner"])
    assert Product.objects.filter(pk=shop["router"].product_id).exists()


def test_delivery_cost_larger_than_the_goods_is_added_to_their_cost_not_refused(shop):
    receipt = receive(shop, 2, 100, landed_costs=[{"description": "Boda boda from town", "amount": "300", "paid_by": "CASH"}])
    lot = StockLot.objects.get(variant=shop["router"])
    assert lot.unit_cost == D("250.0000")  # 100 BP + 300 delivery ÷ 2 units
    assert balance("1200") == D("500.00") and receipt.landed_cost_total == D("300")
    assert_every_journal_balances()


def test_a_payment_reversed_as_not_real_is_not_money_received(shop):
    from apps.accounting.models import CashEntry
    from apps.accounting.services import reverse
    receive(shop, 2, 300)
    sale = sell(shop, 1, price=1000, paid_amount=0)
    payment = collect(sale=sale, amount=D("1000"), method="CASH", key="pay")
    reverse(entry=CashEntry.objects.get(source_key=f"payment:{payment.pk}"), user=shop["owner"], reason="Cash never arrived")
    today = timezone.localdate()
    assert statements.owner_summary(today, today)["money_received"]["amount"] == D("0.00")
    assert sale_balance(sale) == D("1000.00") and balance("1100") == D("1000.00") and balance("1000") == 0
    assert_every_journal_balances()


def test_payments_cannot_exceed_what_is_owed_after_a_credit_note(shop):
    receive(shop, 2, 300)
    sale = sell(shop, 1, price=1000, paid_amount=0)
    adjust_sale_price(sale=sale, kind="CREDIT", amount=D("200"), reason="Scratched box", user=shop["owner"])
    with pytest.raises(ValidationError):
        collect(sale=sale, amount=D("1000"), method="CASH", key="over")
    collect(sale=sale, amount=D("800"), method="CASH", key="exact")
    assert sale_balance(sale) == 0 and balance("1100") == 0


def test_full_return_refund_does_not_collide_with_a_partial_return_refund(shop):
    from apps.commerce.settlements import return_sale
    receive(shop, 10, 300)
    whole, partly = sell(shop, 1, price=1000), sell(shop, 2, price=1000)
    payment = whole.payments.get()
    partial = return_items(sale=partly, lines=[{"item_id": partly.items.get().pk, "quantity": 1, "restock": True}], reason="Changed mind",
                           user=shop["owner"], refund={"method": "CASH", "amount": "1000"})
    return_sale(sale=whole, user=shop["owner"], reason="Faulty")  # once keyed "refund:<payment id>", like the partial refund
    whole_journals = {j["source"] for j in statements.explain_sale_item(whole.items.get().pk)["journals"]}
    partly_journals = {j["source"] for j in statements.explain_sale_item(partly.items.get().pk)["journals"]}
    assert {f"return:{whole.pk}", f"payment-refund:{payment.pk}"} <= whole_journals and f"refund:{partial.pk}" not in whole_journals
    assert f"refund:{partial.pk}" in partly_journals and f"payment-refund:{payment.pk}" not in partly_journals
    assert_every_journal_balances()


def test_reversing_commission_takes_it_out_of_revenue_too(shop):
    from apps.accounting.models import CashEntry
    from apps.accounting.services import reverse
    from apps.mpesa.models import MpesaOutlet
    from apps.mpesa.services import record_commission
    outlet = MpesaOutlet.objects.create(store=Store.objects.get(), display_name="Agent till")
    commission = record_commission(outlet=outlet, user=shop["owner"], period=timezone.localdate(), commission_amount=D("135"),
                                   reference="COMM-SEP", settlement_method="MPESA")
    entry = CashEntry.objects.get(source_key=f"commission:{commission.pk}")
    assert entry.branch_id == outlet.store_id
    reverse(entry=entry, user=shop["owner"], reason="Provider clawed it back")
    assert statements.profit_and_loss(None, None)["revenue"] == 0 and balance("1020") == 0
    assert_every_journal_balances()


def test_refunds_and_delivery_costs_are_not_reversed_from_the_cash_book(shop):
    from apps.accounting.models import CashEntry
    from apps.accounting.services import reverse
    receive(shop, 5, 400, landed_costs=[{"description": "Transport", "amount": "100", "paid_by": "CASH"}])
    sale = sell(shop, 2, price=1000)
    ret = return_items(sale=sale, lines=[{"item_id": sale.items.get().pk, "quantity": 1, "restock": True}], reason="Changed mind",
                       user=shop["owner"], refund={"method": "CASH", "amount": "1000"})
    for key in [f"refund:{ret.pk}", CashEntry.objects.get(source_key__startswith="landed:").source_key]:
        with pytest.raises(ValidationError):
            reverse(entry=CashEntry.objects.get(source_key=key), user=shop["owner"], reason="Mistake")


def test_money_lent_leaves_cash_but_not_profit_and_comes_back_with_repayments(shop):
    from apps.accounting.loans import cancel_loan, lend, outstanding, repay, reverse_repayment, status
    from apps.accounting.models import CashEntry
    from apps.accounting.services import reverse
    today = timezone.localdate()
    loan = lend(user=shop["owner"], borrower_name="Mary Achieng", borrower_phone="0712345678", amount="5000", method="CASH",
                due_date=today + timedelta(days=7), key="loan-1")
    assert lend(user=shop["owner"], borrower_name="Mary Achieng", amount="5000", method="CASH", due_date=today, key="loan-1") == loan  # retry
    assert balance("1000") == D("-5000.00") and balance("1150") == D("5000.00")
    assert statements.profit_and_loss(None, None)["net_profit_before_tax"] == 0  # lending is not a cost
    assert statements.owner_summary(today, today)["position"]["money_lent_out"] == D("5000.00")
    with pytest.raises(ValidationError):  # corrected from the Money lent page only, so books stay in step
        reverse(entry=CashEntry.objects.get(pk=loan.entry_id), user=shop["owner"], reason="Mistake")
    repay(loan=loan, user=shop["owner"], amount="2000", method="CASH", key="r1")
    assert (outstanding(loan), status(loan)) == (D("3000.00"), "PARTLY_REPAID")
    with pytest.raises(ValidationError, match="M-Pesa code"):
        repay(loan=loan, user=shop["owner"], amount="1000", method="MPESA", key="r2")
    with pytest.raises(ValidationError, match="Only 3,000.00"):
        repay(loan=loan, user=shop["owner"], amount="3500", method="CASH", key="r3")
    assert status(loan, today=today + timedelta(days=8)) == "OVERDUE"
    with pytest.raises(ValidationError, match="repaid"):
        cancel_loan(loan=loan, user=shop["owner"], reason="Wrong person")
    last = repay(loan=loan, user=shop["owner"], amount="3000", method="MPESA", reference="sjk4abc123", key="r4")
    assert (last.reference, status(loan), balance("1150"), balance("1000"), balance("1020")) == (
        "SJK4ABC123", "REPAID", 0, D("-3000.00"), D("3000.00"))
    reverse_repayment(repayment=last, user=shop["owner"], reason="M-Pesa code did not match")
    assert (outstanding(loan), balance("1150"), balance("1020")) == (D("3000.00"), D("3000.00"), 0)
    assert {r["key"]: r for r in statements.reconciliation()}["loans"]["reconciled"]
    assert statements.profit_and_loss(None, None)["net_profit_before_tax"] == 0
    assert_every_journal_balances()


def test_a_loan_recorded_by_mistake_is_cancelled_and_its_money_returns(shop):
    from apps.accounting.loans import cancel_loan, lend, outstanding, status
    today = timezone.localdate()
    with pytest.raises(ValidationError, match="payback date"):
        lend(user=shop["owner"], borrower_name="Tom", amount="100", method="CASH", due_date=today - timedelta(days=1), key="bad")
    loan = lend(user=shop["owner"], borrower_name="Tom Kip", amount="1500", method="MPESA", due_date=today, key="loan-2")
    cancel_loan(loan=loan, user=shop["owner"], reason="Typed twice")
    loan.refresh_from_db()
    assert (status(loan), outstanding(loan), balance("1150"), balance("1020")) == ("CANCELLED", 0, 0, 0)
    assert_every_journal_balances()


def test_dashboard_counts_opening_stock_receipts_as_opening_stock_not_purchases(shop):
    from rest_framework.test import APIClient
    from apps.inventory.models import StockReceipt
    receive(shop, 3, 160, document_status=StockReceipt.OPENING_BALANCE)  # already owned
    receive(shop, 2, 500)  # bought from a supplier
    client = APIClient()
    client.force_authenticate(shop["owner"])
    period = client.get("/api/v1/inventory/dashboard/").json()["period_summary"]
    assert Decimal(str(period["purchases"])) == D("1000.00")
    assert Decimal(str(period["opening_stock"])) == D("480.00")


def test_stock_found_in_a_count_adds_to_stock_but_never_to_profit(shop):
    from rest_framework.test import APIClient
    from apps.inventory.adjustments import adjust_stock
    from apps.inventory.models import StockBalance
    receive(shop, 2, 120)
    balance_row = StockBalance.objects.get()
    adjust_stock(user=shop["owner"], variant_id=shop["router"].pk, shelf_id=balance_row.shelf_id, expected_quantity="2",
                 counted_quantity="3", reason="Found stock", idempotency_key="count-1", confirmed=True, lot_id=balance_row.lot_id)
    client = APIClient()
    client.force_authenticate(shop["owner"])
    today = client.get("/api/v1/inventory/dashboard/").json()["today"]
    assert Decimal(str(today["expenses"])) == 0  # no bills were recorded
    assert Decimal(str(today["stock_corrections"])) == 0
    assert Decimal(str(today["profit"])) == 0  # profit only comes from selling
    assert balance("1200") == D("360.00") and balance("3000") == D("-120.00")  # the found unit joins opening stock
    assert_every_journal_balances()


def test_dashboard_collections_and_top_items_follow_credit_notes_and_returns(shop):
    from rest_framework.test import APIClient
    receive(shop, 5, 300)
    bargained = sell(shop, 1, price=1000)  # recorded at 1,000, really sold for 700
    adjust_sale_price(sale=bargained, kind="CREDIT", amount=D("300"), reason="Bargained", user=shop["owner"])
    returned = sell(shop, 2, price=1000, paid_amount=D("1000"), customer=shop["owner"])  # one paid, one owed
    return_items(sale=returned, lines=[{"item_id": returned.items.get().pk, "quantity": 1, "restock": True}], reason="Changed mind", user=shop["owner"])
    client = APIClient()
    client.force_authenticate(shop["owner"])
    data = client.get("/api/v1/inventory/dashboard/").json()
    money = lambda v: Decimal(str(v))
    collections = data["collections"]
    assert money(collections["period_billed"]) == D("1700.00")  # 700 + (2,000 − 1,000 returned)
    assert money(collections["collected_on_period_sales"]) == D("1700.00")
    assert money(collections["period_outstanding"]) == 0
    router = data["top_items"][0]
    assert (money(router["quantity"]), money(router["sales"])) == (D("2.000"), D("1700.00"))
    assert money(data["period_summary"]["revenue"]) == D("1700.00")  # same figure as the books
    shop_part = next(unit for unit in data["unit_period"] if unit["key"] == "SHOP")  # the analysis' "where the sales came from"
    assert money(shop_part["revenue"]) == D("1700.00") and money(shop_part["profit"]) == money(data["period_summary"]["profit"])


def test_adding_a_product_whose_code_belongs_to_a_hidden_product_says_so_plainly(shop):
    from apps.catalog.models import Product
    from apps.inventory.services import create_product_with_opening_stock
    Product.objects.filter(pk=shop["router"].product_id).update(active=False)  # hidden, not deleted: it has history
    with pytest.raises(ValidationError) as refused:
        create_product_with_opening_stock(user=shop["owner"], product_data={"name": "Router again", "category": shop["category"]},
                                          variant_data={"sku": "RTR-1", "selling_price": 1000})
    message = str(refused.value.detail["sku"])
    assert "RTR-1 already belongs to Wi-Fi router" in message and "tick Active" in message


def test_products_are_hidden_with_records_kept_or_removed_only_when_they_have_no_history(shop):
    from rest_framework.test import APIClient
    from apps.catalog.models import Product
    from apps.inventory.services import create_product_with_opening_stock
    receive(shop, 3, 400)
    sell(shop, 1)
    router = shop["router"].product
    spare, _ = create_product_with_opening_stock(user=shop["owner"], product_data={"name": "Spare cable", "category": shop["category"]},
                                                 variant_data={"sku": "SPARE-1", "selling_price": 100})
    client = APIClient()
    client.force_authenticate(shop["owner"])
    check = {row["name"]: row for row in client.post("/api/v1/catalog/products/delete-check/", {"ids": [router.pk, spare.pk]}, format="json").json()}
    assert check["Wi-Fi router"]["can_remove"] is False and "sold" in check["Wi-Fi router"]["reason"] and check["Spare cable"]["can_remove"] is True
    refused = client.post("/api/v1/catalog/products/bulk-delete/", {"ids": [router.pk, spare.pk], "mode": "remove"}, format="json")
    assert refused.status_code == 400 and Product.objects.filter(pk=spare.pk).exists()  # nothing happens unless the rest may be hidden
    done = client.post("/api/v1/catalog/products/bulk-delete/", {"ids": [router.pk, spare.pk], "mode": "remove", "hide_rest": True}, format="json").json()
    assert {row["name"]: row["result"] for row in done} == {"Wi-Fi router": "hidden", "Spare cable": "removed"}
    assert not Product.objects.filter(pk=spare.pk).exists() and Product.objects.get(pk=router.pk).active is False
    assert Sale.objects.count() == 1  # the router's sale is kept
    assert_every_journal_balances()


def test_product_overview_shows_category_path_stock_sales_after_corrections_and_history(shop):
    from rest_framework.test import APIClient
    receive(shop, 3, 400)
    sale = sell(shop, 1, price=1000)
    adjust_sale_price(sale=sale, kind="CREDIT", amount=D("300"), reason="Bargained", user=shop["owner"])
    client = APIClient()
    client.force_authenticate(shop["owner"])
    data = client.get(f"/api/v1/catalog/products/{shop['router'].product_id}/overview/").json()
    assert data["category_path"] == ["Networking"]
    assert (D(data["stock"]["on_shelf"]), D(data["stock"]["value_at_cost"])) == (D("2"), D("800.00"))
    recent = data["sales_30_days"]
    assert (D(recent["quantity"]), D(recent["revenue"]), D(recent["profit"])) == (D("1"), D("700.00"), D("300.00"))  # after the credit note
    assert [row["what"] for row in data["activity"]] == ["Sold", "Received from supplier"]
    assert data["deliveries"][0]["supplier"] == "Tech Supplies"



def test_return_after_credit_note_never_refunds_more_than_was_paid(shop):
    receive(shop, 2, 300)
    sale = sell(shop, 1, price=500)  # paid 500 at the till
    item = sale.items.get()
    adjust_sale_price(sale=sale, kind="CREDIT", amount=D("150"), reason="Bargained", user=shop["owner"], idempotency_key="n1")
    # After the note the item is charged at 350; the customer paid 500, so 150 is already owed back to them.
    back = return_items(sale=sale, lines=[{"item_id": item.pk, "quantity": 1}], reason="Faulty", user=shop["owner"], idempotency_key="r1")
    assert back.lines.get().payable_amount == D("350.00")
    assert sale_balance(sale) == -D("500.00")  # the customer is owed exactly what they paid, no more
    with pytest.raises(ValidationError, match="can still be returned"):
        return_items(sale=sale, lines=[{"item_id": item.pk, "quantity": 1}], reason="Again", user=shop["owner"], idempotency_key="r2")
    assert_every_journal_balances()


def test_credit_note_cannot_exceed_what_is_left_after_a_return(shop):
    receive(shop, 2, 300)
    sale = sell(shop, 2, price=500)
    item = sale.items.get()
    return_items(sale=sale, lines=[{"item_id": item.pk, "quantity": 1}], reason="Faulty", user=shop["owner"], idempotency_key="r1")
    with pytest.raises(ValidationError, match="still charged"):
        adjust_sale_price(sale=sale, kind="CREDIT", amount=D("600"), reason="Too much", user=shop["owner"], idempotency_key="n1")
    adjust_sale_price(sale=sale, kind="CREDIT", amount=D("500"), reason="Gift", user=shop["owner"], idempotency_key="n2")
    assert_every_journal_balances()


def test_dashboard_reversed_collection(shop):
    from apps.accounting.models import CashEntry
    from apps.accounting.services import reverse
    from apps.inventory.dashboard import money_received
    receive(shop, 1, 100)
    sale = sell(shop, 1)
    entry = CashEntry.objects.get(source_key=f'payment:{sale.payments.get().pk}')
    reverse(entry=entry, user=shop['owner'], reason='Payment never happened')
    today = timezone.localdate()
    assert money_received(today, today) == D('0')

@pytest.mark.parametrize("mode", ["restock", "damaged", "full"])
def test_return_after_cost_supplied(shop, mode):
    receipt = receive(shop, 0, 0, document_status='OPENING_BALANCE', supplier='',
        lines=[{'variant_id': shop['router'].pk, 'received_quantity': '1', 'unit_cost': '0', 'uncosted': True}])
    sale = sell(shop, 1)
    correct_lot_cost(lot=receipt.lines.get().lot, unit_cost=D('450'), reason='Found invoice', user=shop['owner'])
    if mode == 'full':
        from apps.commerce.settlements import return_sale
        return_sale(sale=sale, user=shop['owner'], reason='Returned')
    else:
        return_items(sale=sale, lines=[{'item_id': sale.items.get().pk, 'quantity': 1, 'restock': mode == 'restock'}], reason='Returned', user=shop['owner'])
    assert balance('1200') == (D('0') if mode == 'damaged' else D('450'))
    assert balance('6100') == (D('450') if mode == 'damaged' else D('0'))
    assert balance('5000') == D('0')
    assert_every_journal_balances()


def test_whole_sale_credit_after_partial_return(shop):
    receive(shop, 2, 100)
    from apps.inventory.services import complete_sale
    sale = complete_sale(lines=[{'variant': shop['router'], 'quantity': 1}, {'variant': shop['router'], 'quantity': 1}], channel='POS', number='AUDIT', user=shop['owner'])
    first, second = list(sale.items.all())
    return_items(sale=sale, lines=[{'item_id': first.pk, 'quantity': 1}], reason='Returned first', user=shop['owner'])
    adjust_sale_price(sale=sale, kind='CREDIT', amount=D('500'), reason='Discount remaining goods', user=shop['owner'])
    return_items(sale=sale, lines=[{'item_id': second.pk, 'quantity': 1}], reason='Returned remaining', user=shop['owner'])
    from apps.commerce.returns import sale_amounts, item_sales
    assert all(amount == 0 for quantity, amount in item_sales(sale).values())
    assert balance("4000") == 0
    assert sale_amounts(sale)[0] == D('0')


def test_dashboard_full_refund_and_partial_refund_match_accounts(shop):
    from apps.commerce.settlements import return_sale
    from apps.inventory.dashboard import money_received
    receive(shop, 4, 100)
    full, partial = sell(shop, 1), sell(shop, 2)
    return_sale(sale=full, user=shop['owner'], reason='Returned')
    return_items(sale=partial, lines=[{'item_id': partial.items.get().pk, 'quantity': 1}],
                 reason='Returned', user=shop['owner'], refund={'method': 'CASH', 'amount': '1000'})
    today = timezone.localdate()
    assert money_received(today, today) == D('1000')
    assert money_received(today, today) == statements.owner_summary(today, today)['money_received']['amount']


@pytest.mark.parametrize("kind", ["CREDIT", "DEBIT"])
def test_note_allocation_stays_fixed_through_taxed_returns(shop, kind):
    from apps.tenancy.models import Organization
    from apps.tenancy.context import organization_id
    from apps.commerce.returns import sale_amounts, item_sales
    organization = Organization.objects.get(pk=organization_id())
    organization.settings = {**organization.settings, 'tax': {'enabled': True, 'rate': '0.16', 'inclusive': True}}
    organization.save(update_fields=['settings'])
    receive(shop, 3, 100)
    sale = complete_sale(lines=[{'variant': shop['router'], 'quantity': 1} for _ in range(3)],
                         channel='POS', number='TAXED-NOTE', user=shop['owner'])
    items = list(sale.items.order_by('pk'))
    return_items(sale=sale, lines=[{'item_id': items[0].pk, 'quantity': 1}], reason='First return', user=shop['owner'])
    note = adjust_sale_price(sale=sale, kind=kind, amount=D('333.33'), reason='Price correction', user=shop['owner'])
    assert str(items[0].pk) not in note.line_amounts
    assert sum((D(a['net']) + D(a['tax']) for a in note.line_amounts.values()), D(0)) == note.amount
    for item in reversed(items[1:]):
        return_items(sale=sale, lines=[{'item_id': item.pk, 'quantity': 1}], reason='Remaining return', user=shop['owner'])
    assert sale_amounts(sale)[0] == 0
    assert balance('4000') == balance('2200') == 0
    assert all(amount == 0 for quantity, amount in item_sales(sale).values())
    assert_every_journal_balances()


def test_opening_stock_buying_price_typed_wrongly_can_be_corrected(shop):
    opening = receive(shop, 0, 0, document_status="OPENING_BALANCE", supplier="",
                      lines=[{"variant_id": shop["router"].pk, "received_quantity": "3", "unit_cost": "150"}])
    lot = opening.lines.get().lot
    sell(shop, 1, price=2000, allow_below_cost=True)
    correct_lot_cost(lot=lot, unit_cost=D("1500"), reason="Typed 150 instead of 1500", user=shop["owner"])
    lot.refresh_from_db()
    assert (lot.unit_cost, opening.lines.get().unit_cost) == (D("1500.0000"), D("1500.00"))
    assert balance("1200") == D("3000.00") and balance("5000") == D("1500.00") and balance("3000") == -D("4500.00")
    assert AuditLog.objects.filter(action="LOT_COST_CORRECTED", object_id=str(lot.pk), before={"unit_cost": "150.0000"}).exists()
    with pytest.raises(ValidationError):
        correct_lot_cost(lot=lot, unit_cost=D("1500"), reason="Same again", user=shop["owner"])
    assert_every_journal_balances()


def test_supplier_buying_price_correction_keeps_delivery_cost_and_what_is_owed(shop):
    from apps.accounting.services import purchase_outstanding
    receipt = receive(shop, 4, 100, landed_costs=[{"description": "Delivery", "amount": "40", "paid_by": "SUPPLIER_INVOICE"}])
    lot = receipt.lines.get().lot
    assert lot.unit_cost == D("110.0000")
    sell(shop, 1, price=500)
    correct_lot_cost(lot=lot, unit_cost=D("120"), reason="Invoice says 120", user=shop["owner"])
    lot.refresh_from_db()
    assert (lot.unit_cost, receipt.lines.get().unit_cost) == (D("130.0000"), D("120.00"))
    assert balance("1200") == D("390.00")  # 3 still held × (120 BP + 10 delivery)
    receipt.refresh_from_db()
    assert purchase_outstanding(type(receipt.purchase).objects.get(receipt=receipt)) == D("520.00")  # 4 × 120 + 40 delivery on the invoice
    assert_every_journal_balances()


def test_buying_prices_are_listed_and_corrected_from_the_product(shop):
    from rest_framework.test import APIClient
    receipt = receive(shop, 2, 300)
    client = APIClient()
    client.force_authenticate(shop["owner"])
    rows = client.get(f"/api/v1/inventory/variants/{shop['router'].pk}/buying-prices/").json()
    assert [(r["source"], D(r["buying_price"]), r["can_correct"]) for r in rows] == [("supplier", D("300"), True)]
    response = client.post(f"/api/v1/inventory/lots/{rows[0]['id']}/cost/", {"unit_cost": "350", "reason": "Mistyped"}, format="json")
    assert response.status_code == 201 and D(response.json()["buying_price"]) == D("350")
    assert receipt.lines.get().unit_cost == D("350.00")
    assert client.post(f"/api/v1/inventory/lots/{rows[0]['id']}/cost/", {"unit_cost": "abc", "reason": "x"}, format="json").status_code == 400
    client.force_authenticate(User.objects.create_user("clerk", password="Clerk-pass-2026", is_staff=True))
    assert client.get(f"/api/v1/inventory/variants/{shop['router'].pk}/buying-prices/").status_code == 403
    assert client.post(f"/api/v1/inventory/lots/{rows[0]['id']}/cost/", {"unit_cost": "1", "reason": "x"}, format="json").status_code == 403


def test_quantity_can_be_raised_from_product_details_at_the_latest_buying_price(shop):
    from rest_framework.test import APIClient
    receive(shop, 2, 300)
    client = APIClient()
    client.force_authenticate(shop["owner"])
    context = client.get(f"/api/v1/inventory/adjustments/variants/{shop['router'].pk}/").json()
    location = context["locations"][0]
    assert context["default_shelf_id"] == location["shelf_id"] and context["latest_lot_id"] == StockLot.objects.get().pk
    response = client.post("/api/v1/inventory/adjustments/", {
        "variant_id": shop["router"].pk, "shelf_id": context["default_shelf_id"], "expected_quantity": "2", "counted_quantity": "5",
        "reason": "Data-entry correction", "notes": "", "confirmed": True, "idempotency_key": "edit-1", "lot_id": context["latest_lot_id"]}, format="json")
    assert response.status_code == 200, response.json()
    assert balance("1200") == D("1500.00")
    assert_every_journal_balances()


def test_products_page_stock_totals_grow_when_stock_arrives_and_shrink_when_it_sells(shop):
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(shop["owner"])
    stock = lambda: client.get("/api/v1/catalog/products/category-counts/").json()["stock"]
    before = stock()
    receive(shop, 5, 300)  # 5 routers at 300 each, selling at 1,000
    after = stock()
    assert Decimal(str(after["units"])) - Decimal(str(before["units"])) == 5
    assert Decimal(str(after["value_at_cost"])) - Decimal(str(before["value_at_cost"])) == D("1500")
    assert Decimal(str(after["value_at_selling_price"])) - Decimal(str(before["value_at_selling_price"])) == D("5000")
    sell(shop, 2)
    sold = stock()
    assert Decimal(str(after["units"])) - Decimal(str(sold["units"])) == 2
    assert Decimal(str(after["value_at_cost"])) - Decimal(str(sold["value_at_cost"])) == D("600")  # what the 2 sold cost


def test_each_sales_profit_is_what_the_books_have_after_returns_and_adds_up_to_the_report(shop):
    receive(shop, 5, 400)
    returned = sell(shop, 3, line={"discount": D("300"), "discount_reason": "Loyal customer"})
    item = returned.items.get()
    return_items(sale=returned, lines=[{"item_id": item.pk, "quantity": 1, "restock": True}], reason="Wrong model", user=shop["owner"])
    kept = sell(shop, 1)
    figures = statements.sale_profits(Sale.objects.filter(pk__in=[returned.pk, kept.pk]).prefetch_related("returns", "adjustments"))
    assert figures[returned.pk] == {"sales": D("1800.00"), "cost": D("800.00"), "profit": D("1000.00")}
    assert figures[kept.pk] == {"sales": D("1000.00"), "cost": D("400.00"), "profit": D("600.00")}
    retail = statements.profit_and_loss(None, None)["units"][0]
    assert (sum(f["sales"] for f in figures.values()), sum(f["cost"] for f in figures.values())) == (retail["revenue"], retail["direct_costs"])


def test_each_sale_adds_its_profit_to_where_profit_had_reached(shop):
    receive(shop, 5, 400)
    first = sell(shop, 1)
    second = sell(shop, 1, price=700)
    reached = statements.running_sale_profits()
    assert (reached[first.pk]["profit"], reached[first.pk]["profit_so_far"]) == (D("600.00"), D("600.00"))
    assert (reached[second.pk]["profit"], reached[second.pk]["profit_so_far"]) == (D("300.00"), D("900.00"))


def test_profit_counts_as_customers_pay_so_it_is_money_the_business_has(shop):
    from apps.accounting.credit_profit import owed_profit
    from apps.inventory.dashboard import accrual_totals, pnl_rows
    receive(shop, 5, 600)
    today = timezone.localdate()
    profit = lambda: accrual_totals(pnl_rows(today, today), ["SHOP"])
    sell(shop, 1, price=1000)  # paid in full: its 400 profit counts at once
    assert (profit()["owed_profit"], profit()["profit"]) == (0, D("400.00"))
    credit = sell(shop, 1, price=1000, paid_amount=0)  # on credit: none of its 400 profit yet
    assert (owed_profit(), profit()["profit"], profit()["revenue"]) == (D("400.00"), D("400.00"), D("2000.00"))
    collect(sale=credit, amount=D("250"), method="CASH", key="quarter")  # a quarter paid: a quarter of its profit
    assert (owed_profit(), profit()["profit"]) == (D("300.00"), D("500.00"))
    owner = statements.owner_summary(today, today)
    assert (owner["net_profit"]["amount"], owner["owed_profit"]["amount"], owner["profit_received"]["amount"]) == (D("800.00"), D("300.00"), D("500.00"))
    collect(sale=credit, amount=D("750"), method="CASH", key="rest")
    assert (owed_profit(), profit()["profit"]) == (0, D("800.00"))


def test_a_credit_sale_returned_owes_no_profit_and_one_paid_later_counts_on_the_day_it_is_paid(shop):
    from apps.accounting.credit_profit import owed_profit, owed_profit_rows
    receive(shop, 5, 600, days_ago=5)
    returned = sell(shop, 1, price=1000, paid_amount=0)
    return_items(sale=returned, lines=[{"item_id": returned.items.get().pk, "quantity": 1, "restock": True}], reason="Changed mind", user=shop["owner"])
    assert owed_profit() == 0
    later = sell(shop, 1, price=1000, paid_amount=0)
    week_ago = timezone.now() - timedelta(days=3)
    Sale.objects.filter(pk=later.pk).update(created_at=week_ago)
    collect(sale=Sale.objects.get(pk=later.pk), amount=D("1000"), method="CASH", key="paid")
    today = timezone.localdate()
    rows = [row for row in owed_profit_rows() if row["amount"] > 0 and row["date"] == timezone.localtime(week_ago).date()]
    assert [r["amount"] for r in rows] == [D("400.00")]  # owed from the sale's day...
    assert sum((r["amount"] for r in owed_profit_rows(today, today)), D(0)) == D("-400.00")  # ...and counted the day it was paid
