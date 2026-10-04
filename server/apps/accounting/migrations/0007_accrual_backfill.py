"""Backfill accrual fields on existing records and guard the new tenant tables.

Assumptions (see docs/accounting-policy.md):
- A historical sale line's list price is taken to be the price it was actually sold at, because the
  catalogue price at the time was not recorded separately before this change.
- A historical sale-level discount is spread across its lines in proportion to their gross value;
  the sale's total is unchanged. No tax was configured before this change, so tax is zero.
- A historical expense was always recorded as paid: its amount, date and branch come from its payment.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations
from apps.tenancy.guards import install_relationship_guards

CENT = Decimal("0.01")
NEW_TABLES = [("commerce", "SaleReturn"), ("commerce", "SaleReturnLine"), ("commerce", "SaleAdjustment"),
              ("inventory", "PurchaseReturn"), ("inventory", "PurchaseReturnLine"), ("inventory", "LotCostCorrection"),
              ("accounting", "Expense"), ("accounting", "ExpensePayment")]


def backfill(apps, schema_editor):
    Sale = apps.get_model("commerce", "Sale")
    SaleItem = apps.get_model("commerce", "SaleItem")
    Expense = apps.get_model("accounting", "Expense")
    for sale in Sale.objects.iterator():
        items = list(SaleItem.objects.filter(sale_id=sale.pk).order_by("pk"))
        if sale.discount and items and not any(item.discount for item in items):
            gross = sum((item.quantity * item.unit_price for item in items), Decimal("0"))
            remaining = sale.discount
            for index, item in enumerate(items):
                share = remaining if index == len(items) - 1 else (
                    (sale.discount * item.quantity * item.unit_price / gross).quantize(CENT, ROUND_HALF_UP) if gross else Decimal("0"))
                item.discount, remaining = share, remaining - share
        for item in items:
            item.list_price = item.list_price if item.list_price is not None else item.unit_price
            item.net_amount = (item.quantity * item.unit_price - item.discount).quantize(CENT, ROUND_HALF_UP)
            item.save(update_fields=["list_price", "discount", "net_amount"])
        Sale.objects.filter(pk=sale.pk).update(net_total=sale.total, tax_total=Decimal("0"))
    for expense in Expense.objects.select_related("entry").iterator():
        if expense.entry_id:
            Expense.objects.filter(pk=expense.pk).update(amount=-expense.entry.amount, incurred_on=expense.entry.occurred_at.date(),
                                                         branch_id=expense.entry.branch_id)
    install_relationship_guards(apps, schema_editor, NEW_TABLES)


class Migration(migrations.Migration):
    dependencies = [("accounting", "0006_accrual_accounting"), ("commerce", "0009_accrual_accounting"),
                    ("inventory", "0015_accrual_accounting")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
