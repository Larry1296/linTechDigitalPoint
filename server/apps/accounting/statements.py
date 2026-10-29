"""Profit and position reports built only from posted journals and recorded cost layers.

Nothing here estimates a cost from a price or treats money received as profit. Amounts that cannot be
relied on yet (unconfirmed payments, uncosted stock, unreconciled balances) are listed, not hidden.
See docs/accounting-policy.md for every formula.
"""
from collections import defaultdict
from decimal import Decimal
from django.db.models import F, Q, Sum
from apps.commerce.models import Payment, Sale, SaleAllocation, SaleItem
from apps.inventory.models import StockBalance, StockLot
from .ledger import CHART
from .models import Expense, JournalEntry, JournalLine, LedgerAccount, SupplierPurchase

ZERO = Decimal("0")
CASH_ACCOUNTS = {code for code, (_, _, is_cash) in CHART.items() if is_cash}
UNITS = [
    {"key": "retail", "name": "Retail shop", "revenue": ["4000", "4030"], "costs": ["5000", "5020"]},
    {"key": "services", "name": "Cyber & services", "revenue": ["4020", "4040"], "costs": ["5010"]},
    {"key": "mpesa", "name": "M-Pesa agency commission", "revenue": ["4010"], "costs": []},
    {"key": "other", "name": "Other income", "revenue": ["4900"], "costs": []},
    {"key": "interest", "name": "Interest on investments", "revenue": ["4910"], "costs": []},
]


def _lines(start=None, end=None):
    rows = JournalLine.objects.all()
    if start:
        rows = rows.filter(entry__posting_date__gte=start)
    if end:
        rows = rows.filter(entry__posting_date__lte=end)
    return rows


def balances(start=None, end=None):
    """{code: {"name", "kind", "debit", "credit", "balance"}} where balance = debit − credit."""
    result = {}
    for row in _lines(start, end).values("account__code", "account__name", "account__kind").annotate(d=Sum("debit"), c=Sum("credit")):
        result[row["account__code"]] = {"code": row["account__code"], "name": row["account__name"], "kind": row["account__kind"],
                                        "debit": row["d"], "credit": row["c"], "balance": row["d"] - row["c"]}
    return result


def _credit(accounts, codes):
    return sum((-accounts[c]["balance"] for c in codes if c in accounts), ZERO)


def _debit(accounts, codes):
    return sum((accounts[c]["balance"] for c in codes if c in accounts), ZERO)


def profit_and_loss(start, end):
    accounts = balances(start, end)
    units = []
    for unit in UNITS:
        revenue, costs = _credit(accounts, unit["revenue"]), _debit(accounts, unit["costs"])
        units.append({"key": unit["key"], "name": unit["name"], "revenue": revenue, "direct_costs": costs, "gross_profit": revenue - costs,
                      "loss": revenue - costs < 0})
    # Running costs only; stock found or missing in counts (6100) is shown on its own line, not as an expense.
    expenses = sorted(({"code": a["code"], "name": a["name"], "amount": a["balance"]} for a in accounts.values()
                       if a["kind"] == "EXPENSE" and a["balance"] and a["code"] != "6100"), key=lambda row: row["code"])
    stock_corrections = accounts.get("6100", {}).get("balance", ZERO)
    gross = sum((u["gross_profit"] for u in units), ZERO)
    total_expenses = sum((e["amount"] for e in expenses), ZERO)
    revenue = sum((u["revenue"] for u in units), ZERO)
    direct = sum((u["direct_costs"] for u in units), ZERO)
    return {"units": units, "revenue": revenue, "direct_costs": direct, "gross_profit": gross, "operating_expenses": expenses,
            "total_operating_expenses": total_expenses, "stock_corrections": stock_corrections,
            "net_profit_before_tax": gross - total_expenses - stock_corrections, "loss": gross - total_expenses - stock_corrections < 0}


def balance_sheet(end):
    accounts = balances(end=end)
    group = defaultdict(list)
    for account in accounts.values():
        group[account["kind"]].append(account)
    assets = sum((a["balance"] for a in group["ASSET"]), ZERO)
    liabilities = -sum((a["balance"] for a in group["LIABILITY"]), ZERO)
    equity = -sum((a["balance"] for a in group["EQUITY"]), ZERO)
    earnings = -sum((a["balance"] for kind in ("REVENUE", "COGS", "EXPENSE") for a in group[kind]), ZERO)
    return {"assets": sorted(({"code": a["code"], "name": a["name"], "amount": a["balance"]} for a in group["ASSET"] if a["balance"]), key=lambda r: r["code"]),
            "liabilities": sorted(({"code": a["code"], "name": a["name"], "amount": -a["balance"]} for a in group["LIABILITY"] if a["balance"]), key=lambda r: r["code"]),
            "equity": sorted(({"code": a["code"], "name": a["name"], "amount": -a["balance"]} for a in group["EQUITY"] if a["balance"]), key=lambda r: r["code"]),
            "total_assets": assets, "total_liabilities": liabilities, "total_equity": equity, "retained_earnings": earnings,
            "difference": assets - liabilities - equity - earnings}


def trial_balance(start, end):
    accounts = balances(start, end)
    rows = [accounts[code] for code in sorted(accounts)]
    return {"rows": rows, "debits": sum((r["debit"] for r in rows), ZERO), "credits": sum((r["credit"] for r in rows), ZERO)}


def _cash_flow_group(entry_lines):
    others = {line.account.code for line in entry_lines if line.account.code not in CASH_ACCOUNTS}
    if "1100" in others:
        return "customers"
    if "2000" in others:
        return "suppliers"
    if "2150" in others or any(code.startswith("6") for code in others):
        return "expenses"
    if "1150" in others:
        return "loans"
    if "1400" in others:
        return "investments"
    if "4010" in others:
        return "commission"
    if "3000" in others:
        return "owner"
    if not others:
        return "transfers"
    return "other"


def cash_flow(start, end):
    """Direct method: money into and out of cash, bank and mobile money, grouped by who it came from or went to."""
    labels = {"customers": "Received from customers (net of refunds)", "suppliers": "Paid to suppliers",
              "expenses": "Paid for expenses", "commission": "Agency commission received", "owner": "Owner money in or out / opening balances",
              "loans": "Money lent out, less repayments", "investments": "Put into investments, less taken out", "transfers": "Between your own cash accounts", "other": "Other"}
    totals = defaultdict(lambda: ZERO)
    entries = JournalEntry.objects.filter(lines__account__code__in=CASH_ACCOUNTS - {"1300", "1310"}).distinct()
    if start:
        entries = entries.filter(posting_date__gte=start)
    if end:
        entries = entries.filter(posting_date__lte=end)
    for entry in entries.prefetch_related("lines__account"):
        lines = list(entry.lines.all())
        amount = sum((l.debit - l.credit for l in lines if l.account.code in CASH_ACCOUNTS - {"1300", "1310"}), ZERO)
        totals[_cash_flow_group(lines)] += amount
    rows = [{"key": key, "label": labels[key], "amount": totals[key]} for key in labels if totals[key]]
    return {"rows": rows, "net": sum(totals.values(), ZERO),
            "note": "M-Pesa agency cash and float are the business's stock for the agency, like goods on the shelves; they are reported with the agency, not here."}


def stock_valuation():
    """Every cost layer still holding stock, valued at its own recorded cost."""
    rows = []
    for balance in (StockBalance.objects.filter(quantity__gt=0).select_related("lot__variant__product", "shelf")
                    .order_by("lot__variant__product__name", "lot__received_at")):
        lot = balance.lot
        rows.append({"lot": lot.pk, "item": str(lot.variant), "sku": lot.variant.sku, "reference": lot.reference, "received_at": lot.received_at,
                     "supplier": lot.supplier_name, "shelf": balance.shelf.code, "quantity": balance.quantity, "unit_cost": lot.unit_cost,
                     "value": (balance.quantity * lot.unit_cost).quantize(Decimal("0.01")), "uncosted": lot.cost_status == StockLot.UNCOSTED})
    return rows


def receivables():
    from apps.commerce.returns import sale_balance
    rows = []
    for sale in Sale.objects.filter(status="COMPLETED").select_related("customer").prefetch_related("payments").order_by("created_at"):
        owed = sale_balance(sale)
        if owed:
            rows.append({"sale": sale.pk, "number": sale.number, "customer": (sale.customer.get_full_name() or sale.customer.username) if sale.customer else "Walk-in",
                         "date": sale.created_at, "due_date": sale.due_date, "total": sale.total, "owed": owed})
    return rows


def payables():
    from .services import expense_outstanding, purchase_outstanding
    suppliers = [{"type": "supplier", "id": p.pk, "name": p.supplier.name if p.supplier else "Supplier not named", "reference": p.receipt.receipt_number,
                  "date": p.receipt.received_at, "owed": purchase_outstanding(p)} for p in SupplierPurchase.objects.select_related("supplier", "receipt")]
    bills = [{"type": "expense", "id": e.pk, "name": e.category.name, "reference": e.description, "date": e.incurred_on, "due_date": e.due_date,
              "owed": expense_outstanding(e)} for e in Expense.objects.select_related("category")]
    return {"suppliers": [r for r in suppliers if r["owed"]], "bills": [r for r in bills if r["owed"] > 0]}


def reconciliation():
    """Sub-ledgers against the general ledger, both as they stand today. The sub-ledgers (stock layers, sale and
    bill balances) only exist as current figures, so comparing them with a past ledger date would show false
    differences. A difference is shown with its likely cause, never hidden."""
    from apps.mpesa.models import MpesaTransaction
    accounts = balances()
    stock = sum((r["value"] for r in stock_valuation() if not r["uncosted"]), ZERO)
    owed_by_customers = sum((r["owed"] for r in receivables()), ZERO)
    owing = payables()
    to_suppliers = sum((r["owed"] for r in owing["suppliers"]), ZERO)
    bills = sum((r["owed"] for r in owing["bills"]), ZERO)
    agency = MpesaTransaction.objects.aggregate(cash=Sum("cash_delta"), float=Sum("float_delta"))
    from .loans import outstanding
    from .models import Loan
    lent = sum((outstanding(loan) for loan in Loan.objects.prefetch_related("repayments")), ZERO)
    from .investments import business_value, settle_books
    from .models import Investment
    settle_books()
    # Only the business's money in investments is in the books; the owner's own money is kept out.
    invested = sum((business_value(i) for i in Investment.objects.all()), ZERO)
    checks = [
        ("inventory", "Stock value (cost layers) vs Stock account", stock, _debit(accounts, ["1200"]),
         "Stock received before the books started, or rounding of fractional quantities (under 1.00)."),
        ("receivables", "Customer balances vs Customer balances account", owed_by_customers, _debit(accounts, ["1100"]),
         "Sales recorded before the books started."),
        ("payables", "Owed to suppliers vs Supplier balances account", to_suppliers, -_debit(accounts, ["2000"]),
         "Stock received through the old single-item receive (no supplier purchase record), or receipts and supplier payments from before the books started."),
        ("accrued_expenses", "Unpaid bills vs Accrued expenses account", bills, -_debit(accounts, ["2150"]),
         "Expenses recorded before accrual accounting started."),
        ("loans", "Money lent (loan list) vs Money lent out account", lent, _debit(accounts, ["1150"]),
         "A loan or repayment corrected outside the Money lent page."),
        ("investments", "Investments (Investments page) vs Investments account", invested, _debit(accounts, ["1400"]),
         "An investment entry corrected outside the Investments page."),
        ("agency_cash", "M-Pesa agency cash (operational ledger) vs Agency cash account", agency["cash"] or ZERO, _debit(accounts, ["1300"]),
         "Agency activity before the books started."),
        ("agency_float", "M-Pesa float (operational ledger) vs Agency float account", agency["float"] or ZERO, _debit(accounts, ["1310"]),
         "Agency activity before the books started."),
    ]
    rows = []
    for key, label, detail, ledger, cause in checks:
        difference = (detail - ledger).quantize(Decimal("0.01"))
        rows.append({"key": key, "label": label, "detail": detail, "ledger": ledger, "difference": difference,
                     "reconciled": abs(difference) < Decimal("1.00"), "explanation": "" if not difference else cause})
    return rows


def warnings_for(start, end):
    """Amounts a reader must know are provisional, pending or incomplete."""
    unconfirmed = Payment.objects.filter(status__in=["PENDING", "MANUAL_REVIEW"], sale__isnull=False)
    uncosted_sold = (SaleAllocation.objects.filter(lot__cost_status=StockLot.UNCOSTED, item__sale__status="COMPLETED")
                     .aggregate(q=Sum("quantity"), revenue=Sum(F("quantity") * F("item__net_amount") / F("item__quantity"))))
    uncosted_held = (StockBalance.objects.filter(lot__cost_status=StockLot.UNCOSTED, quantity__gt=0).aggregate(q=Sum("quantity")))
    items = []
    total_unconfirmed = unconfirmed.aggregate(v=Sum("amount"))["v"] or ZERO
    if total_unconfirmed:
        items.append({"key": "unconfirmed_payments", "amount": total_unconfirmed,
                      "message": "Customer payments not yet confirmed (e.g. M-Pesa awaiting a code). They are still owed, not counted as money received."})
    if uncosted_sold["q"]:
        items.append({"key": "uncosted_sales", "amount": (uncosted_sold["revenue"] or ZERO).quantize(Decimal("0.01")), "quantity": uncosted_sold["q"],
                      "message": "Sales of stock whose buying price was never recorded. Their cost of goods is missing, so gross profit is overstated until the price is supplied under Stock value."})
    if uncosted_held["q"]:
        items.append({"key": "uncosted_stock", "quantity": uncosted_held["q"],
                      "message": "Stock on hand without a buying price. Its value is not included in stock until the price is supplied."})
    for row in reconciliation():
        if not row["reconciled"]:
            items.append({"key": f"unreconciled_{row['key']}", "amount": row["difference"],
                          "message": f"{row['label']} differ by {row['difference']}. {row['explanation']}"})
    return items


def owner_summary(start, end):
    """The simple view, in plain words, with where each number comes from."""
    pl = profit_and_loss(start, end)
    entries = JournalLine.objects.filter(account__code__in=CASH_ACCOUNTS - {"1300", "1310"}, entry__posting_date__gte=start, entry__posting_date__lte=end)
    # Every cash movement against customer balances: payments, refunds, and payments later reversed as not real.
    customer_journals = JournalEntry.objects.filter(lines__account__code="1100")
    received = entries.filter(entry__in=customer_journals).aggregate(v=Sum(F("debit") - F("credit")))["v"] or ZERO
    position = balances(end=end)
    return {
        "sales": {"amount": pl["revenue"], "explain": "Everything sold or earned in the period after discounts and excluding tax, whether paid or not."},
        "money_received": {"amount": received, "explain": "Money customers actually paid in the period (including for older sales), less refunds. This is cash, not profit."},
        "stock_cost": {"amount": pl["direct_costs"], "explain": "What the goods and service materials you sold cost you, from each delivery's recorded buying price (oldest stock first)."},
        "gross_profit": {"amount": pl["gross_profit"], "explain": "Sales minus the cost of what was sold. Not the final profit."},
        "expenses": {"amount": pl["total_operating_expenses"], "explain": "Rent, wages, transport and other running costs you recorded for the period, paid or still owed."},
        "stock_corrections": {"amount": pl["stock_corrections"],
                              "explain": "Stock found or missing when you counted the shelves. Found stock adds to profit; missing stock takes away from it."},
        "net_profit": {"amount": pl["net_profit_before_tax"], "loss": pl["loss"],
                       "explain": "What you made after the cost of what you sold, your running costs and any stock found or missing. Before income tax."},
        "position": {"cash_and_bank": _debit(position, sorted(CASH_ACCOUNTS - {"1300", "1310"})), "customers_owe_you": _debit(position, ["1100"]),
                     "you_owe_suppliers": -_debit(position, ["2000"]), "unpaid_bills": -_debit(position, ["2150"]),
                     "tax_owed": -_debit(position, ["2200"]), "stock_value": _debit(position, ["1200"]),
                     "money_lent_out": _debit(position, ["1150"])},
        "warnings": warnings_for(start, end),
    }


def account_ledger(code, start, end, page=1, size=100):
    """General ledger for one account with a running balance; each line links to its source."""
    account = LedgerAccount.objects.filter(code=code).first()
    if not account:
        return None
    opening = (JournalLine.objects.filter(account=account, entry__posting_date__lt=start).aggregate(v=Sum(F("debit") - F("credit")))["v"] or ZERO) if start else ZERO
    rows = _lines(start, end).filter(account=account).select_related("entry").order_by("entry__posting_date", "entry_id", "pk")
    count = rows.count()
    running = opening + (sum((r.debit - r.credit for r in rows[: (page - 1) * size]), ZERO) if page > 1 else ZERO)
    result = []
    for line in rows[(page - 1) * size: page * size]:
        running += line.debit - line.credit
        result.append({"date": line.entry.posting_date, "journal": line.entry.pk, "source": line.entry.source_key, "description": line.entry.description,
                       "debit": line.debit, "credit": line.credit, "balance": running})
    return {"code": account.code, "name": account.name, "kind": account.kind, "opening": opening, "count": count, "page": page, "rows": result}


def journal_data(entry):
    return {"id": entry.pk, "date": entry.posting_date, "source": entry.source_key, "description": entry.description,
            "reversal_of": entry.reversal_of_id,
            "lines": [{"account": l.account.code, "name": l.account.name, "debit": l.debit, "credit": l.credit} for l in entry.lines.select_related("account")]}


def explain_sale_item(item_id):
    """Traces a sale line's profit to its prices, the stock deliveries it came from, and every journal."""
    item = (SaleItem.objects.select_related("sale__customer", "sale__created_by", "sale__branch", "variant__product").filter(pk=item_id).first())
    if not item:
        return None
    sale = item.sale
    layers = []
    for allocation in item.allocations.select_related("lot", "shelf"):
        lot = allocation.lot
        line = getattr(lot, "receipt_line", None)
        receipt = line.receipt if line else None
        layers.append({"lot": lot.pk, "delivery": lot.reference, "supplier": lot.supplier_name, "received_at": lot.received_at,
                       "receipt": receipt.pk if receipt else None, "supplier_reference": receipt.external_reference if receipt else "",
                       "buying_price": line.unit_cost if line else lot.unit_cost - lot.landed_unit_cost,
                       "landed_cost_per_unit": lot.landed_unit_cost, "unit_cost": allocation.unit_cost, "quantity": allocation.quantity,
                       "cost": (allocation.quantity * allocation.unit_cost).quantize(Decimal("0.01")),
                       "uncosted": lot.cost_status == StockLot.UNCOSTED or (line.uncosted if line else False),
                       "cost_corrections": [{"unit_cost": c.unit_cost, "reason": c.reason, "date": c.created_at} for c in lot.cost_corrections.all()]})
    originals = [f"sale:{sale.pk}"] + [f"payment:{p.pk}" for p in sale.payments.all()]
    keys = originals + [f"return-cost:{sale.pk}"] + [f"sale-return:{r.pk}" for r in sale.returns.all()] + [f"sale-note:{n.pk}" for n in sale.adjustments.all()]
    # "refund:<id>" once also keyed full-return payment reversals by payment id, so a return refund is only one
    # that reverses nothing; reversals of this sale's own journals are found through what they reverse.
    related = (Q(source_key__in=keys) | Q(source_key__in=[f"refund:{r.pk}" for r in sale.returns.all()], reversal_of__isnull=True)
               | Q(reversal_of__source_key__in=originals))
    gross = (item.quantity * item.unit_price).quantize(Decimal("0.01"))
    profit = item.net_amount - item.cost
    return {
        "sale": {"id": sale.pk, "number": sale.number, "date": sale.created_at, "channel": sale.channel, "status": sale.status,
                 "branch": sale.branch.name if sale.branch else "", "cashier": (sale.created_by.get_full_name() or sale.created_by.username) if sale.created_by else "",
                 "customer": (sale.customer.get_full_name() or sale.customer.username) if sale.customer else "Walk-in",
                 "payment_status": _payment_status(sale)},
        "line": {"id": item.pk, "item": str(item.variant), "sku": item.variant.sku, "quantity": item.quantity,
                 "catalogue_price": item.list_price, "actual_price": item.unit_price, "gross": gross,
                 "discount": item.discount, "discount_reason": item.discount_reason, "tax": item.tax_amount, "net_revenue": item.net_amount,
                 "cogs": item.cost, "gross_profit": profit, "loss": profit < 0 and not item.cost_pending, "cost_pending": item.cost_pending,
                 "returned_quantity": item.returned_quantity,
                 "formula": "gross profit = net revenue − COGS; net revenue = quantity × actual price − discount − tax (if tax is included in the price)"},
        "cost_layers": layers,
        "returns": [{"number": r.sale_return.number, "quantity": r.quantity, "restocked": r.restock, "net": r.net_amount, "cost": r.cost_amount,
                     "reason": r.sale_return.reason} for r in item.return_lines.select_related("sale_return")],
        "notes": [{"kind": n.kind, "amount": n.amount, "reason": n.reason, "date": n.created_at} for n in sale.adjustments.all()],
        "journals": [journal_data(e) for e in JournalEntry.objects.filter(related).order_by("posting_date", "pk")],
    }


def _payment_status(sale):
    from apps.commerce.returns import sale_balance
    if sale.status in ("REFUNDED", "CANCELLED"):
        return "REVERSED"
    payments = list(sale.payments.all())
    if payments and all(p.status == "FAILED" for p in payments):
        return "FAILED"
    owed = sale_balance(sale)
    if owed <= 0:
        return "PAID"
    return "PARTLY_PAID" if any(p.status == "COMPLETED" for p in payments) else "UNPAID"


def sale_profits(sales=None):
    """{sale id: {"sales", "cost", "profit"}} for each of ``sales`` (every sale not deleted, when None), as the books
    have it now: what the sale brought in and what the sold items cost, after returns, price corrections and costs found
    later (the same journals the reports add up, so the sales here add up to the reports' figures)."""
    from apps.commerce.models import SaleAdjustment, SaleReturn
    if sales is None:
        ids = list(Sale.objects.exclude(status="CANCELLED").values_list("pk", flat=True))
        returns = SaleReturn.objects.filter(sale_id__in=ids).values_list("pk", "sale_id")
        notes = SaleAdjustment.objects.filter(sale_id__in=ids).values_list("pk", "sale_id")
        keys = Q(entry__source_key__regex=r"^(sale|return-cost|sale-return|sale-note):") | Q(entry__reversal_of__source_key__regex=r"^(sale|sale-return|sale-note):")
    else:
        sales = list(sales)
        ids = [sale.pk for sale in sales]
        returns = [(r.pk, sale.pk) for sale in sales for r in sale.returns.all()]
        notes = [(n.pk, sale.pk) for sale in sales for n in sale.adjustments.all()]
    owner = {}
    for pk in ids:
        owner[f"sale:{pk}"] = owner[f"return-cost:{pk}"] = pk
    owner.update({f"sale-return:{pk}": sale for pk, sale in returns})
    owner.update({f"sale-note:{pk}": sale for pk, sale in notes})
    if sales is not None:
        keys = Q(entry__source_key__in=owner.keys()) | Q(entry__reversal_of__source_key__in=owner.keys())
    result = {pk: {"sales": Decimal("0"), "cost": Decimal("0")} for pk in ids}
    lines = (JournalLine.objects.filter(account__kind__in=["REVENUE", "COGS"]).filter(keys)
             .values("entry__source_key", "entry__reversal_of__source_key", "account__kind").annotate(d=Sum("debit"), c=Sum("credit")))
    for line in lines:
        sale = owner.get(line["entry__source_key"]) or owner.get(line["entry__reversal_of__source_key"])
        if sale is None:
            continue  # a deleted sale's journals
        if line["account__kind"] == "REVENUE":
            result[sale]["sales"] += line["c"] - line["d"]
        else:
            result[sale]["cost"] += line["d"] - line["c"]
    for figures in result.values():
        figures["profit"] = figures["sales"] - figures["cost"]
    return result


def running_sale_profits():
    """{sale id: {"sales", "cost", "profit", "profit_so_far"}} for every sale not deleted: ``profit_so_far`` is the
    profit of that sale added to every sale before it, so each row shows where the sales' profit had reached."""
    figures = sale_profits()
    reached = Decimal("0")
    for pk in Sale.objects.filter(pk__in=figures.keys()).order_by("created_at", "pk").values_list("pk", flat=True):
        reached += figures[pk]["profit"]
        figures[pk]["profit_so_far"] = reached
    return figures
