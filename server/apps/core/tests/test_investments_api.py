"""Investments page: money put into an MMF and taken out, whose it is, interest from the statement, corrections.
The business's money moves between its places and the investment and stays the business's; the owner's own money is
never in the books. All the interest (less fees, from the statements) is the business's profit, kept in the investment."""
from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient
from apps.core.models import Store
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def shop():
    owner = User.objects.create_user("investor", password="Safe-pass-1848")
    cashier = User.objects.create_user("invest-till", password="Safe-pass-1848")
    org = Organization.objects.create(name="Invest shop", slug="invest", owner=owner)
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    Membership.objects.create(user=cashier, organization=org, role="CASHIER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        store = Store.objects.create(name="Main")
    client = APIClient()
    client.force_login(owner)
    return client, org, owner, cashier, store


def _mmf(client):
    made = client.post("/api/v1/accounting/investments/", {"name": "Sanlam MMF", "account_number": "MMF-0042"}, format="json")
    assert made.status_code == 201, made.content
    return made.json()["id"]


def _move(client, mmf, kind, amount, source, key, **extra):
    return client.post(f"/api/v1/accounting/investments/{mmf}/move/", {"kind": kind, "amount": amount, "source": source,
                       "idempotency_key": key, **extra}, format="json")


def _books(org):
    with organization_context(org):
        from apps.accounting import statements
        return statements.balances(), statements.reconciliation(), statements.profit_and_loss(None, None)


def _untouched(org, earned=D("0")):
    """None of the owner's own money is in the business's books; what it earned (interest less fees) is the business's
    profit, kept in the investment as the business's money (1400). No place and no owner money changes."""
    accounts, checks, pl = _books(org)
    balance = lambda code: accounts.get(code, {"balance": D("0")})["balance"]
    assert all(balance(code) == 0 for code in ("1000", "1010", "1020", "1030", "3000"))
    assert (-balance("4910") - balance("6200"), balance("1400")) == (earned, earned)
    assert next(c for c in checks if c["key"] == "investments")["reconciled"] and pl["net_profit_before_tax"] == earned


def test_money_in_and_out_stay_out_of_the_books_and_only_the_interest_is_profit(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    week_ago = timezone.localdate() - timedelta(days=7)
    put = _move(client, mmf, "DEPOSIT", "20000", "OWNER", "in-1", occurred_on=str(week_ago), reference="sjk4abc123")
    assert put.status_code == 201, put.content
    assert D(put.json()["value"]) == D("20000") and put.json()["movements"][0]["occurred_on"] == str(week_ago)
    assert put.json()["movements"][0]["reference"] == "SJK4ABC123"
    # The same click again records nothing new.
    assert len(_move(client, mmf, "DEPOSIT", "20000", "OWNER", "in-1", occurred_on=str(week_ago)).json()["movements"]) == 1
    interest = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "20150", "idempotency_key": "st-1"}, format="json")
    assert interest.status_code == 201, interest.content
    row = interest.json()
    assert (D(row["value"]), D(row["interest"]), row["movements"][0]["kind"]) == (D("20150"), D("150"), "INTEREST")
    assert client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "20150", "idempotency_key": "st-2"},
                       format="json").status_code == 400  # nothing changed
    too_much = _move(client, mmf, "WITHDRAWAL", "30000", "OWNER", "out-big")
    # The interest is the business's, so only the 20,000 put in is the owner's own to take out.
    assert too_much.status_code == 400 and "only holds 20,000.00 of your own money" in str(too_much.json())
    out = _move(client, mmf, "WITHDRAWAL", "5000", "OWNER", "out-1")
    assert out.status_code == 201 and D(out.json()["value"]) == D("15150")
    # Only the interest is the business's profit; no money moved through the business's places.
    _untouched(org, earned=D("150"))
    with organization_context(org):
        from apps.accounting.models import CashEntry
        assert not CashEntry.objects.exists()
    assert D(client.get("/api/v1/accounting/investments/").json()["total_value"]) == D("15150")


def test_the_till_drawer_bank_agency_and_business_money_are_never_used(shop):
    client, org, owner, _, store = shop
    from apps.mpesa.models import MpesaOutlet
    from apps.mpesa.services import open_session
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "1000", "OWNER", "own")
    with organization_context(org):
        session = open_session(outlet=MpesaOutlet.objects.create(store=store, display_name="Agency"), operator=owner,
                               opening_cash="50000", opening_float="30000")
    for source in ("CASH", "MPESA", "BANK", "OTHER", "AGENCY_CASH", "AGENCY_FLOAT", "EARLIER"):
        for kind in ("DEPOSIT", "WITHDRAWAL"):
            assert _move(client, mmf, kind, "100", source, f"{source}-{kind}", session_id=session.pk).status_code == 400
    with organization_context(org):
        from apps.accounting import investments
        from rest_framework.exceptions import ValidationError
        from apps.accounting.models import Investment
        with pytest.raises(ValidationError, match="Say whose money it is"):
            investments.move(investment=Investment.objects.get(pk=mmf), user=owner, kind="DEPOSIT", amount="100", source="MPESA", key="direct")
        with pytest.raises(ValidationError, match="Choose where the business's money comes from"):
            investments.move(investment=Investment.objects.get(pk=mmf), user=owner, kind="DEPOSIT", amount="100", source="BUSINESS",
                             place="AGENCY_FLOAT", key="agency")
    # The desk cannot move agency money into an investment either.
    assert client.post("/api/v1/mpesa/transactions/", {"session": session.pk, "transaction_type": "INVESTMENT", "amount": "1",
                       "cash_delta": "-1", "float_delta": "0", "idempotency_key": "sneak"}, format="json").status_code == 400
    # Nor can money in it be marked as the business's.
    own = client.get("/api/v1/accounting/investments/").json()["investments"][0]["movements"][0]["id"]
    assert client.post(f"/api/v1/accounting/investments/movements/{own}/business/", {}, format="json").status_code == 400
    _untouched(org)


def test_the_owners_own_money_goes_in_without_touching_the_business_money(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    # Far more than the business holds (nothing): it is the owner's money from outside.
    put = _move(client, mmf, "DEPOSIT", "500000", "OWNER", "own-in")
    assert put.status_code == 201, put.content
    assert D(put.json()["value"]) == D("500000") and put.json()["movements"][0]["source"] == "OWNER"
    out = _move(client, mmf, "WITHDRAWAL", "100000", "OWNER", "own-out")
    assert out.status_code == 201 and D(out.json()["value"]) == D("400000")
    # It is not the business's money, so it never enters the books: no investment, no owner capital, no profit.
    accounts, checks, pl = _books(org)
    assert all(accounts.get(code, {"balance": D("0")})["balance"] == 0 for code in ("1000", "1010", "1020", "1400", "3000"))
    assert next(c for c in checks if c["key"] == "investments")["reconciled"] and pl["net_profit_before_tax"] == 0
    assert (D(out.json()["from_owner"]), D(out.json()["from_shop"]), D(out.json()["shop_value"])) == (D("400000"), D("0"), D("0"))
    first = next(m for m in out.json()["movements"] if m["kind"] == "WITHDRAWAL")["id"]
    assert client.post(f"/api/v1/accounting/investments/movements/{first}/undo/", {"reason": "Wrong"}, format="json").status_code == 200
    accounts, *_ = _books(org)
    assert accounts.get("1400", {"balance": D("0")})["balance"] == 0


def _legacy(org, investment, kind, amount, source, key, method=None, business=None, purchase=None, days_ago=10):
    """A record as it was kept before investment money was kept apart: money moved through a business place, with
    the business's share posted to the books."""
    from apps.accounting.ledger import paired, post_journal
    from apps.accounting.models import InvestmentMovement
    from apps.accounting.services import post
    day = timezone.localdate() - timedelta(days=days_ago)
    entry = None
    if method:
        entry = post(unit="SHOP", method=method, amount=-D(amount) if kind == "DEPOSIT" else D(amount), kind="INVESTMENT",
                     reference=f"Old {kind}", key=f"investment:{key}", journal=False)
    m = InvestmentMovement.objects.create(investment=investment, kind=kind, amount=D(amount), business_amount=business, occurred_on=day,
                                          source=source, entry=entry, purchase=purchase, idempotency_key=key)
    lines = {"DEPOSIT": paired("1400", "1020" if method == "MPESA" else "3000", D(amount)),
             "WITHDRAWAL": paired("1020" if method == "MPESA" else "1030", "1400", D(amount)),
             "INTEREST": paired("1400", "4910", D(amount))}[kind]
    post_journal(key=f"investment:{m.pk}", description=f"Old {kind}", lines=lines, date=day)
    return m


def test_records_from_before_are_kept_apart_from_the_business_once(shop):
    client, org, owner, _, store = shop
    mmf = _mmf(client)
    with organization_context(org):
        from apps.accounting.models import CashEntry, Investment, InvestmentMovement, JournalEntry
        from apps.accounting.services import link_receipt, pay_purchase, purchase_outstanding
        investment = Investment.objects.get(pk=mmf)
        _legacy(org, investment, "DEPOSIT", "30000", "EARLIER", "old-in", business=D("30000"), days_ago=20)
        _legacy(org, investment, "INTEREST", "400", "", "old-interest", business=None)
        _legacy(org, investment, "WITHDRAWAL", "5000", "MPESA", "old-till", method="MPESA", business=D("5000"))
        _legacy(org, investment, "WITHDRAWAL", "10700", "OTHER", "old-other", method="OTHER", business=D("10700"))
        # Stock paid with money taken out of the investment into the till and straight on to the supplier.
        receipt = _receive(org, owner, _stock(org, store), None, "INV-9")
        purchase = link_receipt(receipt)
        _legacy(org, investment, "WITHDRAWAL", "2000", "MPESA", "receipt:INV-9:investment", method="MPESA", business=D("2000"), purchase=purchase)
        pay_purchase(purchase=purchase, amount=D("2000"), method="MPESA", key="receipt:INV-9", user=owner, reference="INV-9")
    before = client.get("/api/v1/accounting/investments/").json()["investments"][0]
    assert D(before["value"]) == D("12700")  # 30,000 + 400 − 5,000 − 10,700 − 2,000
    money = client.get("/api/v1/accounting/money-check/").json()
    expected = {p["method"]: D(p["expected"]) for p in money["places"]}
    # The till and "other" hold only the business's own money; the supplier stays paid, with the owner's own money.
    assert expected["MPESA"] == 0 and expected.get("OTHER", D("0")) == 0
    # Their investment entries were taken back out, so nothing is kept in investments from the business's places.
    assert all(D(str(part["amount"])) == 0 for place in money["places"] for part in place["parts"] if part["key"] == "invested")
    owner_money = [s for s in money["starting"] if not s["can_undo"]]
    assert [D(s["amount"]) for s in owner_money] == [D("2000")] and "Owner's own money from Sanlam MMF" in owner_money[0]["note"]
    accounts, checks, pl = _books(org)
    # The owner's 2,000 that paid the supplier is in the books as the owner's money put in (3000), and the 400 interest
    # as profit, kept in the investment as the business's money.
    assert all(accounts.get(code, {"balance": D("0")})["balance"] == 0 for code in ("1020", "1030"))
    assert (accounts["4910"]["balance"], accounts["1400"]["balance"], accounts["3000"]["balance"], pl["net_profit_before_tax"]) == (D("-400"), D("400"), D("-2000"), D("400"))
    assert next(c for c in checks if c["key"] == "investments")["reconciled"]
    row = client.get("/api/v1/accounting/investments/").json()["investments"][0]
    assert D(row["value"]) == D("12700") and all(m["source"] in ("OWNER", "") for m in row["movements"])
    till = next(m for m in row["movements"] if D(m["amount"]) == D("5000"))
    assert "first recorded into the Lipa na M-Pesa till" in till["note"]
    with organization_context(org):
        assert purchase_outstanding(purchase) == D("18000")  # the 2,000 paid stays paid
        assert not InvestmentMovement.objects.exclude(business_amount=0).exclude(whose="BUSINESS").exists()
        counts = (CashEntry.objects.count(), JournalEntry.objects.count())
    client.get("/api/v1/accounting/money-check/")  # done once: nothing more happens
    with organization_context(org):
        assert (CashEntry.objects.count(), JournalEntry.objects.count()) == counts


def test_a_lower_statement_is_a_fee_and_mistakes_are_undone_in_order(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    deposit = _move(client, mmf, "DEPOSIT", "1000", "OWNER", "in-1").json()["movements"][0]["id"]
    fee = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "990", "idempotency_key": "st-1"}, format="json").json()
    assert (fee["movements"][0]["kind"], D(fee["fees"]), D(fee["value"])) == ("FEE", D("10"), D("990"))
    out = _move(client, mmf, "WITHDRAWAL", "990", "OWNER", "out-1").json()["movements"][0]["id"]
    blocked = client.post(f"/api/v1/accounting/investments/movements/{deposit}/undo/", {"reason": "Wrong fund"}, format="json")
    assert blocked.status_code == 400 and "Undo that first" in str(blocked.json())
    assert client.post(f"/api/v1/accounting/investments/movements/{out}/undo/", {"reason": "Wrong fund"}, format="json").status_code == 200
    assert client.post(f"/api/v1/accounting/investments/movements/{fee['movements'][0]['id']}/undo/", {"reason": "x"}, format="json").status_code == 200
    undone = client.post(f"/api/v1/accounting/investments/movements/{deposit}/undo/", {"reason": "Wrong fund"}, format="json")
    assert undone.status_code == 200 and D(undone.json()["value"]) == D("0")
    _untouched(org)


def test_each_investment_has_a_kind_and_its_risk(shop):
    client, *_ = shop
    sacco = client.post("/api/v1/accounting/investments/", {"name": "Stima Sacco", "kind": "SACCO", "annual_rate": "11"}, format="json").json()
    assert (sacco["kind"]["label"], sacco["kind"]["risk_label"], sacco["fund"]) == ("Sacco deposits", "Low to medium", None)
    # Following a fund's published rate makes it that fund's money market fund.
    kcb = client.post("/api/v1/accounting/investments/", {"name": "KCB MMF", "kind": "EQUITY"}, format="json").json()
    assert kcb["fund"]["code"] == "KCB_MMF_KES" and kcb["kind"]["code"] == "MMF" and kcb["kind"]["risk_label"] == "Low"
    assert client.post("/api/v1/accounting/investments/", {"name": "Mystery", "kind": "CRYPTO"}, format="json").status_code == 400


def test_an_investment_recorded_by_mistake_is_removed_and_everything_in_it_undone(shop):
    client, org, owner, cashier, _ = shop
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "20000", "OWNER", "in-1", occurred_on=str(timezone.localdate() - timedelta(days=3)))
    _move(client, mmf, "DEPOSIT", "5000", "OWNER", "in-own")  # more added to what is already in it
    client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "25100", "idempotency_key": "st"}, format="json")
    _move(client, mmf, "WITHDRAWAL", "3000", "OWNER", "out")
    assert D(client.get("/api/v1/accounting/investments/").json()["total_value"]) == D("22100")
    till = APIClient()
    till.force_login(cashier)
    assert till.post(f"/api/v1/accounting/investments/{mmf}/remove/", {"reason": "x"}, format="json").status_code == 403
    assert client.post(f"/api/v1/accounting/investments/{mmf}/remove/", {"reason": ""}, format="json").status_code == 400
    assert client.post(f"/api/v1/accounting/investments/{mmf}/remove/", {"reason": "Entered twice"}, format="json").status_code == 204
    listed = client.get("/api/v1/accounting/investments/").json()
    assert listed["investments"] == [] and D(listed["total_value"]) == 0
    _untouched(org)
    assert _move(client, mmf, "DEPOSIT", "100", "OWNER", "late").status_code == 400
    # The name is free again for the right account.
    assert client.post("/api/v1/accounting/investments/", {"name": "Sanlam MMF"}, format="json").status_code == 201


def test_cashiers_cannot_see_or_move_investments(shop):
    client, org, _, cashier, _ = shop
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "500", "OWNER", "in-1")
    till = APIClient()
    till.force_login(cashier)
    assert till.get("/api/v1/accounting/investments/").status_code == 403
    assert _move(till, mmf, "DEPOSIT", "1", "OWNER", "in-2").status_code == 403
    assert client.post("/api/v1/accounting/investments/", {"name": "sanlam mmf"}, format="json").status_code == 400


def test_money_check_follows_only_the_businesss_money_put_into_or_taken_out_of_an_investment(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    client.post("/api/v1/accounting/money-check/starting/", {"method": "MPESA", "amount": "80000", "idempotency_key": "start"}, format="json")
    assert _move(client, mmf, "DEPOSIT", "50000", "OWNER", "sweep").status_code == 201
    assert _move(client, mmf, "WITHDRAWAL", "10000", "OWNER", "back").status_code == 201
    with organization_context(org):
        from apps.accounting.money_check import expected
        total, parts = expected("MPESA")
    assert total == D("80000") and parts["invested"] == 0  # the owner's own money: the till is untouched
    assert _move(client, mmf, "DEPOSIT", "30000", "BUSINESS", "biz", place="MPESA").status_code == 201
    with organization_context(org):
        total, parts = expected("MPESA")
    assert (total, parts["invested"]) == (D("50000"), D("-30000"))


def _stock(org, store):
    from apps.catalog.models import Category, Product, ProductVariant
    with organization_context(org):
        category = Category.objects.create(name="Phones", slug="phones")
        return ProductVariant.objects.create(product=Product.objects.create(name="Phone", slug="phone", category=category),
                                             name="Basic", sku="PH-1", selling_price=3000)


def _receive(org, user, variant, payment, number):
    from apps.inventory.services import complete_stock_receipt
    with organization_context(org):
        return complete_stock_receipt(supplier_name="Phone Hub", external_reference=number, user=user, payment=payment,
                                      lines=[{"variant_id": variant.pk, "received_quantity": "10", "unit_cost": "2000"}])


def test_stock_paid_from_the_mmf_is_the_owners_own_money_paying_the_supplier(shop):
    client, org, owner, _, store = shop
    mmf = _mmf(client)
    assert _move(client, mmf, "DEPOSIT", "50000", "OWNER", "sweep").status_code == 201
    receipt = _receive(org, owner, _stock(org, store), {"method": "INVESTMENT", "investment_id": mmf, "via": "MPESA", "amount": "20000"}, "INV-77")
    with organization_context(org):
        from apps.accounting.models import SupplierPurchase
        from apps.accounting.money_check import expected
        from apps.accounting.services import purchase_outstanding
        from apps.accounting.supplier_settlement import receipt_balance, undo_payment
        assert purchase_outstanding(SupplierPurchase.objects.get(receipt=receipt)) == 0
        # The till never saw it: the owner's money came in as "other" money and went straight to the supplier.
        assert expected("MPESA")[0] == 0 and expected("OTHER")[0] == 0
        payment = receipt_balance(receipt)["payments"][0]
        assert payment["source"] == "INVESTMENT"
    row = client.get("/api/v1/accounting/investments/").json()["investments"][0]
    taken = row["movements"][0]
    assert (D(row["value"]), taken["kind"], taken["source"]) == (D("30000"), "WITHDRAWAL", "OWNER")
    assert taken["purchase"]["receipt_number"] == "INV-77" and taken["purchase"]["supplier"] == "Phone Hub"
    accounts, checks, pl = _books(org)
    assert accounts.get("1400", {"balance": D("0")})["balance"] == 0 and accounts["2000"]["balance"] == D("0")
    assert next(c for c in checks if c["key"] == "investments")["reconciled"] and pl["net_profit_before_tax"] == D("0")
    # Undoing the payment puts the money back in the investment and the supplier is owed again.
    with organization_context(org):
        undo_payment(receipt=receipt, entry_id=payment["id"], reason="Wrong receipt", user=owner)
        assert purchase_outstanding(SupplierPurchase.objects.get(receipt=receipt)) == D("20000") and expected("OTHER")[0] == 0
    assert D(client.get("/api/v1/accounting/investments/").json()["total_value"]) == D("50000")


def test_stock_cannot_be_paid_from_the_mmf_beyond_its_value_or_by_a_cashier(shop):
    from rest_framework.exceptions import ValidationError
    client, org, owner, cashier, store = shop
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "5000", "OWNER", "in")
    phone = _stock(org, store)
    with pytest.raises(ValidationError, match="only holds 5,000.00"):
        _receive(org, owner, phone, {"method": "INVESTMENT", "investment_id": mmf, "via": "BANK", "amount": "20000"}, "INV-1")
    with pytest.raises(ValidationError, match="not allowed to take money out of investments"):
        _receive(org, cashier, phone, {"method": "INVESTMENT", "investment_id": mmf, "via": "BANK", "amount": "1000"}, "INV-2")
    with organization_context(org):
        from apps.inventory.models import StockReceipt
        assert not StockReceipt.objects.exists()  # nothing half-recorded
    assert D(client.get("/api/v1/accounting/investments/").json()["total_value"]) == D("5000")


def _rate(org, mmf, month, rate):
    from apps.accounting.models import Investment, InvestmentRate
    with organization_context(org):
        InvestmentRate.objects.create(investment=Investment.objects.get(pk=mmf), month=month, annual_rate=D(rate), recorded_on=month)


def _estimate(org, mmf, today):
    from apps.accounting.investment_interest import estimate
    from apps.accounting.models import Investment
    with organization_context(org):
        return estimate(Investment.objects.get(pk=mmf), today=today)


def _days(org, mmf, today):
    from apps.accounting.investment_interest import day_by_day
    from apps.accounting.models import Investment
    with organization_context(org):
        return day_by_day(Investment.objects.get(pk=mmf), today=today)


def test_interest_is_estimated_daily_and_added_after_tax_at_each_month_end(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    start = (timezone.localdate().replace(day=1) - timedelta(days=70)).replace(day=1)  # the first of a month at least two months ago
    month_end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    next_month = month_end + timedelta(days=1)
    assert _estimate(org, mmf, month_end) is None  # nothing invested and no rate yet
    _move(client, mmf, "DEPOSIT", "100000", "OWNER", "in", occurred_on=str(start))
    assert _estimate(org, mmf, month_end) is None  # no rate recorded: nothing to estimate from
    _rate(org, mmf, start, "12")
    _rate(org, mmf, next_month, "10")
    first = _estimate(org, mmf, month_end)
    days = (month_end - start).days
    gross = D("100000") * D("0.12") / 365 * days
    assert (first["since"], first["days"], first["rate"]) == (start, days, D("12.000"))
    assert first["gross"] == gross.quantize(D("0.01")) and first["net"] == (gross * D("0.85")).quantize(D("0.01"))
    assert first["value"] == D("100000") + first["net"]
    # Ten days into the next month: the first month's interest, after tax, now earns interest too, at the new rate.
    later = _estimate(org, mmf, next_month + timedelta(days=9))
    expected = gross + (D("100000") + gross * D("0.85")) * D("0.10") / 365 * 10
    assert later["gross"] == expected.quantize(D("0.01")) and later["rate"] == D("10.000")
    # Day by day from the day the money went in, newest first: invested, what each day added and the total after it.
    rows = _days(org, mmf, next_month + timedelta(days=9))
    today, yesterday, first = rows[0], rows[1], rows[-1]
    assert (first["date"], first["invested"], first["moved"], first["interest"], first["value"]) == (start, D("100000"), D("100000"), 0, D("100000"))
    assert len(rows) == (next_month + timedelta(days=9) - start).days + 1 and today["value"] == later["value"]
    assert abs(today["interest"] - (D("100000") + gross * D("0.85")) * D("0.10") / 365 * D("0.85")) <= D("0.01")
    assert today["value"] - yesterday["value"] == today["interest"] and today["interest_so_far"] == later["net"]
    assert sum(r["interest"] for r in rows) == later["net"] and next(r for r in rows if r["date"] == month_end)["rate"] == D("12.000")
    # Money taken out stops earning from that day: the total drops by it and the interest after is on what is left.
    _move(client, mmf, "WITHDRAWAL", "40000", "OWNER", "out", occurred_on=str(next_month + timedelta(days=5)))
    after = _estimate(org, mmf, next_month + timedelta(days=9))
    rows = _days(org, mmf, next_month + timedelta(days=9))
    out_day = next(r for r in rows if r["date"] == next_month + timedelta(days=5))
    assert (out_day["moved"], out_day["invested"]) == (D("-40000"), D("60000")) and rows[0]["value"] == after["value"]
    left = D("60000") + gross * D("0.85")
    expected = gross + (D("100000") + gross * D("0.85")) * D("0.10") / 365 * 5 + left * D("0.10") / 365 * 5
    assert after["gross"] == expected.quantize(D("0.01")) and after["value"] == D("60000") + after["net"]
    # A statement: that day takes the statement's figure and the days after build on it, still ending at the estimate.
    client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "61000", "idempotency_key": "st",
                "occurred_on": str(next_month + timedelta(days=7))}, format="json")
    rows = _days(org, mmf, next_month + timedelta(days=9))
    statement = next(r for r in rows if r["date"] == next_month + timedelta(days=7))
    assert statement["statement"] and statement["value"] == D("61000") and statement["interest_so_far"] == D("1000")
    assert rows[0]["value"] == _estimate(org, mmf, next_month + timedelta(days=9))["value"] > D("61000")


def test_monthly_check_records_the_rate_and_the_statement_interest_and_reminds_until_done(shop):
    client, org, owner, cashier, _ = shop
    mmf = _mmf(client)
    other = client.post("/api/v1/accounting/investments/", {"name": "CIC MMF", "annual_rate": "13.5", "tax_rate": "15"}, format="json").json()
    assert D(str(other["current_rate"]["annual_rate"])) == D("13.5") and not other["check_due"]  # nothing in it yet
    _move(client, mmf, "DEPOSIT", "50000", "OWNER", "in")
    _move(client, other["id"], "DEPOSIT", "20000", "OWNER", "in-cic")
    reminder = client.get("/api/v1/accounting/investments/reminder/").json()
    assert [row["name"] for row in reminder["due"]] == ["Sanlam MMF"]  # CIC already has this month's rate
    listed = client.get("/api/v1/accounting/investments/").json()
    sanlam = next(i for i in listed["investments"] if i["id"] == mmf)
    assert sanlam["check_due"] and sanlam["estimate"] is None and listed["this_month"] == reminder["month"]
    checked = client.post(f"/api/v1/accounting/investments/{mmf}/monthly/", {"annual_rate": "12.8", "balance": "50410", "idempotency_key": "m-1"}, format="json")
    assert checked.status_code == 201, checked.content
    row = checked.json()
    assert not row["check_due"] and D(str(row["current_rate"]["annual_rate"])) == D("12.8") and D(str(row["current_rate"]["statement_balance"])) == D("50410")
    assert (D(row["value"]), D(row["interest"]), row["movements"][0]["kind"]) == (D("50410"), D("410"), "INTEREST")
    assert row["estimate"]["days"] == 0 and D(str(row["estimate"]["net"])) == 0  # just checked against the statement
    # The same click again changes nothing; a later correction this month replaces the rate without a second row.
    again = client.post(f"/api/v1/accounting/investments/{mmf}/monthly/", {"annual_rate": "12.8", "balance": "50410", "idempotency_key": "m-1"}, format="json").json()
    assert len([m for m in again["movements"] if m["kind"] == "INTEREST"]) == 1
    fixed = client.post(f"/api/v1/accounting/investments/{mmf}/monthly/", {"annual_rate": "12.75", "idempotency_key": "m-2"}, format="json").json()
    assert [D(str(r["annual_rate"])) for r in fixed["rates"]] == [D("12.75")] and D(str(fixed["rates"][0]["statement_balance"])) == D("50410")
    assert client.get("/api/v1/accounting/investments/reminder/").json()["due"] == []
    assert client.post(f"/api/v1/accounting/investments/{mmf}/monthly/", {"annual_rate": "130", "idempotency_key": "m-3"}, format="json").status_code == 400
    _untouched(org, earned=D("410"))  # the interest is the business's profit
    client.force_login(cashier)
    assert client.post(f"/api/v1/accounting/investments/{mmf}/monthly/", {"annual_rate": "1", "idempotency_key": "m-4"}, format="json").status_code == 403
    assert client.get("/api/v1/accounting/investments/reminder/").status_code == 403


def test_own_money_dated_earlier_earns_from_that_day_and_each_statement_keeps_the_apps_prediction(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    start = (timezone.localdate().replace(day=1) - timedelta(days=40)).replace(day=1)
    month_end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    # Recorded today, but the money went in on the first of a past month, from the owner's own pocket.
    _move(client, mmf, "DEPOSIT", "100000", "OWNER", "own-earlier", occurred_on=str(start))
    _rate(org, mmf, start, "12")
    predicted = _estimate(org, mmf, month_end)
    assert predicted["since"] == start and predicted["days"] == (month_end - start).days
    row = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "100900", "idempotency_key": "st",
                      "occurred_on": str(month_end)}, format="json").json()
    check = row["statements"][0]
    assert check["date"] == str(month_end) and check["since"] == str(start)
    assert D(str(check["predicted"])) == predicted["net"] and D(str(check["actual"])) == D("900")
    assert D(str(check["difference"])) == D("900") - predicted["net"]
    # Nothing came out of the business: the cash book has no entry for it.
    from apps.accounting.models import CashEntry
    with organization_context(org):
        assert not CashEntry.objects.exists()


def test_interest_is_in_the_dashboard_profit_on_its_statement_date_and_undo_takes_it_out(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "10000", "OWNER", "in", occurred_on=str(timezone.localdate() - timedelta(days=40)))
    day = timezone.localdate().replace(day=1)
    earned = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "10120", "occurred_on": str(day), "idempotency_key": "st"},
                         format="json").json()
    period = client.get(f"/api/v1/inventory/dashboard/?start={day}&end={timezone.localdate()}").json()["period_summary"]
    assert (D(str(period["interest"])), D(str(period["profit"])), D(str(period["revenue"]))) == (D("120"), D("120"), D("0"))
    _untouched(org, earned=D("120"))
    with organization_context(org):
        from apps.accounting.models import JournalEntry
        assert JournalEntry.objects.get(source_key=f"investment-interest:{earned['movements'][0]['id']}").posting_date == day
    lower = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "10100", "idempotency_key": "st-2"}, format="json").json()
    _untouched(org, earned=D("100"))  # fees come out of the interest
    for movement in [m for m in lower["movements"] if m["kind"] in ("INTEREST", "FEE")]:
        assert client.post(f"/api/v1/accounting/investments/movements/{movement['id']}/undo/", {"reason": "test"}, format="json").status_code == 200
    _untouched(org)
    period = client.get(f"/api/v1/inventory/dashboard/?start={day}&end={timezone.localdate()}").json()["period_summary"]
    assert D(str(period["interest"])) == 0 and D(str(period["profit"])) == 0


def test_interest_recorded_before_it_counted_is_brought_into_profit_once(shop):
    client, org, owner, *_ = shop
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "5000", "OWNER", "in")
    with organization_context(org):  # interest as it was recorded before: on the Investments page, not in the books
        from apps.accounting.models import InvestmentMovement
        InvestmentMovement.objects.create(investment_id=mmf, kind="INTEREST", amount=D("60"), business_amount=D("0"), statement_balance=D("5060"),
                                          occurred_on=timezone.localdate(), idempotency_key="old-interest", created_by=owner)
        from apps.accounting.models import JournalEntry
        assert not JournalEntry.objects.filter(source_key__startswith="investment-earned:").exists()
    client.get("/api/v1/inventory/dashboard/")
    _untouched(org, earned=D("60"))
    client.get("/api/v1/inventory/dashboard/")
    _untouched(org, earned=D("60"))


def test_the_business_money_moves_from_its_place_into_the_investment_and_stays_the_businesss(shop):
    client, org, owner, *_ = shop
    mmf = _mmf(client)
    with organization_context(org):
        from apps.accounting.services import post
        post(unit="SHOP", method="MPESA", amount=D("12000"), kind="INCOME", reference="Sales", key="sales-1", user=owner)
    money = lambda: {p["method"]: D(str(p["expected"])) for p in client.get("/api/v1/accounting/money-check/").json()["places"]}
    shop_money = lambda: D(str(client.get("/api/v1/inventory/parts/SHOP/").json()["money"]["amount"]))
    before = shop_money()
    # More than the till has is refused; whose money it is must be said, with the place for the business's.
    too_much = _move(client, mmf, "DEPOSIT", "15000", "BUSINESS", "too-much", place="MPESA")
    assert too_much.status_code == 400 and "only has 12,000.00" in str(too_much.json())
    assert _move(client, mmf, "DEPOSIT", "100", "BUSINESS", "no-place").status_code == 400
    put = _move(client, mmf, "DEPOSIT", "10000", "BUSINESS", "biz-in", place="MPESA")
    assert put.status_code == 201, put.content
    _move(client, mmf, "DEPOSIT", "5000", "OWNER", "own-in")
    row = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "15300", "idempotency_key": "st"}, format="json").json()
    # The till went down; the business's money in the investment is what it put in plus all the interest.
    assert money()["MPESA"] == D("2000")
    assert (D(str(row["shop_value"])), D(str(row["owner_value"]))) == (D("10300"), D("5000"))
    listed = client.get("/api/v1/accounting/investments/").json()
    assert (D(str(listed["shop_value"])), D(str(listed["owner_value"]))) == (D("10300"), D("5000"))
    assert row["movements"][-1]["whose"] == "BUSINESS"
    accounts, _, pl = _books(org)
    assert (accounts["1400"]["balance"], pl["net_profit_before_tax"]) == (D("10300"), D("300"))
    # The shop's own money is the same: it is only kept somewhere else.
    assert shop_money() == before
    # Taking out: no more than each one holds.
    assert _move(client, mmf, "WITHDRAWAL", "6000", "OWNER", "own-too-much").status_code == 400
    assert _move(client, mmf, "WITHDRAWAL", "11000", "BUSINESS", "biz-too-much", place="CASH").status_code == 400
    back = _move(client, mmf, "WITHDRAWAL", "3000", "BUSINESS", "biz-out", place="CASH").json()
    assert money()["CASH"] == D("3000") and D(str(back["shop_value"])) == D("7300")
    # Undone: the money goes back where it was.
    biz_in = next(m for m in back["movements"] if m["kind"] == "DEPOSIT" and m["whose"] == "BUSINESS")["id"]
    blocked = client.post(f"/api/v1/accounting/investments/movements/{biz_in}/undo/", {"reason": "x"}, format="json")
    assert blocked.status_code == 400 and "Undo that first" in str(blocked.json())
    biz_out = next(m for m in back["movements"] if m["kind"] == "WITHDRAWAL")["id"]
    assert client.post(f"/api/v1/accounting/investments/movements/{biz_out}/undo/", {"reason": "Wrong"}, format="json").status_code == 200
    assert money()["CASH"] == 0


def test_stock_paid_from_the_mmf_uses_the_businesss_money_in_it_first(shop):
    client, org, owner, _, store = shop
    mmf = _mmf(client)
    with organization_context(org):
        from apps.accounting.services import post
        post(unit="SHOP", method="MPESA", amount=D("3000"), kind="INCOME", reference="Sales", key="sales", user=owner)
    _move(client, mmf, "DEPOSIT", "3000", "BUSINESS", "biz", place="MPESA")
    _move(client, mmf, "DEPOSIT", "10000", "OWNER", "own")
    with organization_context(org):
        from apps.accounting.investments import pay_supplier
        from apps.accounting.services import link_receipt, purchase_outstanding
        from apps.accounting.supplier_settlement import restocking
        receipt = _receive(org, owner, _stock(org, store), None, "INV-5")
        purchase = link_receipt(receipt)
        pay_supplier(investment_id=mmf, purchase=purchase, amount=D("5000"), key="receipt:INV-5", user=owner)
        assert purchase_outstanding(purchase) == D("15000")
        paid = restocking(timezone.localdate(), timezone.localdate())
    row = client.get("/api/v1/accounting/investments/").json()["investments"][0]
    assert (D(str(row["shop_value"])), D(str(row["owner_value"]))) == (D("0"), D("8000"))
    # The business's 3,000 is its money put back into stock; the owner's 2,000 is the owner's own.
    assert (paid["business"], paid["investment"]) == (D("3000"), D("2000"))
    money = {p["method"]: D(str(p["expected"])) for p in client.get("/api/v1/accounting/money-check/").json()["places"]}
    assert money["MPESA"] == 0 and money.get("OTHER", D("0")) == 0
