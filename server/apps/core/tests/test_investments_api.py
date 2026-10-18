"""Investments page: money put into an MMF and taken out, interest from the statement, agency money, corrections."""
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


def test_money_in_interest_and_money_out_keep_the_books_and_profit_right(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    week_ago = timezone.localdate() - timedelta(days=7)
    put = _move(client, mmf, "DEPOSIT", "20000", "MPESA", "in-1", occurred_on=str(week_ago), reference="sjk4abc123")
    assert put.status_code == 201, put.content
    assert D(put.json()["value"]) == D("20000") and put.json()["movements"][0]["occurred_on"] == str(week_ago)
    assert put.json()["movements"][0]["reference"] == "SJK4ABC123"
    # The same click again records nothing new.
    assert len(_move(client, mmf, "DEPOSIT", "20000", "MPESA", "in-1", occurred_on=str(week_ago)).json()["movements"]) == 1
    interest = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "20150", "idempotency_key": "st-1"}, format="json")
    assert interest.status_code == 201, interest.content
    row = interest.json()
    assert (D(row["value"]), D(row["interest"]), row["movements"][0]["kind"]) == (D("20150"), D("150"), "INTEREST")
    assert client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "20150", "idempotency_key": "st-2"},
                       format="json").status_code == 400  # nothing changed
    too_much = _move(client, mmf, "WITHDRAWAL", "30000", "CASH", "out-big")
    assert too_much.status_code == 400 and "only holds 20,150.00" in str(too_much.json())
    out = _move(client, mmf, "WITHDRAWAL", "5000", "CASH", "out-1")
    assert out.status_code == 201 and D(out.json()["value"]) == D("15150")
    accounts, checks, pl = _books(org)
    assert accounts["1400"]["balance"] == D("15150")
    assert accounts["1020"]["balance"] == D("-20000") and accounts["1000"]["balance"] == D("5000")
    assert next(c for c in checks if c["key"] == "investments")["reconciled"]
    # Moving money is not profit; only the interest is.
    assert pl["net_profit_before_tax"] == D("150") and next(u for u in pl["units"] if u["key"] == "interest")["revenue"] == D("150")
    listed = client.get("/api/v1/accounting/investments/").json()
    assert D(listed["total_value"]) == D("15150") and listed["agency_sessions"] == []


def test_the_owners_own_money_goes_in_without_touching_the_business_money(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    # Far more than the business holds (nothing): it is the owner's money from outside.
    put = _move(client, mmf, "DEPOSIT", "500000", "OWNER", "own-in")
    assert put.status_code == 201, put.content
    assert D(put.json()["value"]) == D("500000") and put.json()["movements"][0]["source"] == "OWNER"
    out = _move(client, mmf, "WITHDRAWAL", "100000", "OWNER", "own-out")
    assert out.status_code == 201 and D(out.json()["value"]) == D("400000")
    accounts, checks, pl = _books(org)
    assert accounts["1400"]["balance"] == D("400000") and accounts["3000"]["balance"] == D("-400000")
    assert all(accounts.get(code, {"balance": D("0")})["balance"] == 0 for code in ("1000", "1010", "1020"))
    assert next(c for c in checks if c["key"] == "investments")["reconciled"] and pl["net_profit_before_tax"] == 0
    first = next(m for m in out.json()["movements"] if m["kind"] == "WITHDRAWAL")["id"]
    assert client.post(f"/api/v1/accounting/investments/movements/{first}/undo/", {"reason": "Wrong"}, format="json").status_code == 200
    accounts, *_ = _books(org)
    assert accounts["1400"]["balance"] == D("500000") and accounts["3000"]["balance"] == D("-500000")


def test_a_lower_statement_is_a_fee_and_mistakes_are_undone_in_order(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    deposit = _move(client, mmf, "DEPOSIT", "1000", "BANK", "in-1").json()["movements"][0]["id"]
    fee = client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "990", "idempotency_key": "st-1"}, format="json").json()
    assert (fee["movements"][0]["kind"], D(fee["fees"]), D(fee["value"])) == ("FEE", D("10"), D("990"))
    out = _move(client, mmf, "WITHDRAWAL", "990", "BANK", "out-1").json()["movements"][0]["id"]
    blocked = client.post(f"/api/v1/accounting/investments/movements/{deposit}/undo/", {"reason": "Wrong fund"}, format="json")
    assert blocked.status_code == 400 and "Undo that first" in str(blocked.json())
    assert client.post(f"/api/v1/accounting/investments/movements/{out}/undo/", {"reason": "Wrong fund"}, format="json").status_code == 200
    assert client.post(f"/api/v1/accounting/investments/movements/{fee['movements'][0]['id']}/undo/", {"reason": "x"}, format="json").status_code == 200
    undone = client.post(f"/api/v1/accounting/investments/movements/{deposit}/undo/", {"reason": "Wrong fund"}, format="json")
    assert undone.status_code == 200 and D(undone.json()["value"]) == D("0")
    accounts, checks, _ = _books(org)
    assert accounts["1400"]["balance"] == D("0") and accounts["1010"]["balance"] == D("0")
    assert next(c for c in checks if c["key"] == "investments")["reconciled"]


def test_agency_cash_goes_into_the_mmf_through_the_open_shift(shop):
    client, org, owner, _, store = shop
    from apps.mpesa.models import MpesaOutlet
    from apps.mpesa.services import open_session, session_balances
    mmf = _mmf(client)
    refused = _move(client, mmf, "DEPOSIT", "10000", "AGENCY_CASH", "agency-0")
    assert refused.status_code == 400 and "Open the M-Pesa agency shift" in str(refused.json())
    with organization_context(org):
        outlet = MpesaOutlet.objects.create(store=store, display_name="Agency")
        session = open_session(outlet=outlet, operator=owner, opening_cash="50000", opening_float="30000")
    assert client.get("/api/v1/accounting/investments/").json()["agency_sessions"][0]["outlet"] == "Agency"
    put = _move(client, mmf, "DEPOSIT", "40000", "AGENCY_CASH", "agency-1")
    assert put.status_code == 201, put.content
    back = _move(client, mmf, "WITHDRAWAL", "5000", "AGENCY_FLOAT", "agency-2")
    assert back.status_code == 201 and D(back.json()["value"]) == D("35000")
    with organization_context(org):
        assert session_balances(session) == (D("10000.00"), D("35000.00"))
        from apps.mpesa.models import MpesaTransaction
        moved = MpesaTransaction.objects.get(transaction_type="INVESTMENT", cash_delta=D("-40000"))
    # The desk cannot reverse it on its own; the Investments page undoes both sides together.
    assert client.post(f"/api/v1/mpesa/transactions/{moved.pk}/reverse/", {"reason": "x", "idempotency_key": "r1"}, format="json").status_code == 400
    assert client.post("/api/v1/mpesa/transactions/", {"session": session.pk, "transaction_type": "INVESTMENT", "amount": "1",
                       "cash_delta": "-1", "float_delta": "0", "idempotency_key": "sneak"}, format="json").status_code == 400
    first = next(m for m in back.json()["movements"] if m["source"] == "AGENCY_CASH")["id"]
    second = next(m for m in back.json()["movements"] if m["source"] == "AGENCY_FLOAT")["id"]
    assert client.post(f"/api/v1/accounting/investments/movements/{second}/undo/", {"reason": "Not done"}, format="json").status_code == 200
    assert client.post(f"/api/v1/accounting/investments/movements/{first}/undo/", {"reason": "Not done"}, format="json").status_code == 200
    with organization_context(org):
        assert session_balances(session) == (D("50000.00"), D("30000.00"))
    accounts, checks, pl = _books(org)
    assert accounts.get("1400", {"balance": D("0")})["balance"] == D("0")
    assert all(c["reconciled"] for c in checks if c["key"] in {"investments", "agency_cash", "agency_float"})
    assert pl["net_profit_before_tax"] == D("0")


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
    _move(client, mmf, "DEPOSIT", "20000", "MPESA", "in-1", occurred_on=str(timezone.localdate() - timedelta(days=3)))
    _move(client, mmf, "DEPOSIT", "5000", "OWNER", "in-own")  # more added to what is already in it
    client.post(f"/api/v1/accounting/investments/{mmf}/statement/", {"balance": "25100", "idempotency_key": "st"}, format="json")
    _move(client, mmf, "WITHDRAWAL", "3000", "CASH", "out")
    assert D(client.get("/api/v1/accounting/investments/").json()["total_value"]) == D("22100")
    till = APIClient()
    till.force_login(cashier)
    assert till.post(f"/api/v1/accounting/investments/{mmf}/remove/", {"reason": "x"}, format="json").status_code == 403
    assert client.post(f"/api/v1/accounting/investments/{mmf}/remove/", {"reason": ""}, format="json").status_code == 400
    assert client.post(f"/api/v1/accounting/investments/{mmf}/remove/", {"reason": "Entered twice"}, format="json").status_code == 204
    listed = client.get("/api/v1/accounting/investments/").json()
    assert listed["investments"] == [] and D(listed["total_value"]) == 0
    accounts, checks, pl = _books(org)
    assert all(accounts.get(code, {"balance": D("0")})["balance"] == 0 for code in ("1400", "1000", "1020", "3000"))
    assert next(c for c in checks if c["key"] == "investments")["reconciled"] and pl["net_profit_before_tax"] == 0
    assert _move(client, mmf, "DEPOSIT", "100", "MPESA", "late").status_code == 400
    # The name is free again for the right account.
    assert client.post("/api/v1/accounting/investments/", {"name": "Sanlam MMF"}, format="json").status_code == 201


def test_cashiers_cannot_see_or_move_investments_and_the_cash_book_cannot_undo_them(shop):
    client, org, _, cashier, _ = shop
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "500", "CASH", "in-1")
    till = APIClient()
    till.force_login(cashier)
    assert till.get("/api/v1/accounting/investments/").status_code == 403
    assert _move(till, mmf, "DEPOSIT", "1", "CASH", "in-2").status_code == 403
    with organization_context(org):
        from apps.accounting.models import CashEntry
        from apps.accounting.services import reverse
        from rest_framework.exceptions import ValidationError
        with pytest.raises(ValidationError, match="Investments page"):
            reverse(entry=CashEntry.objects.get(kind="INVESTMENT"), user=None, reason="x")
    assert client.post("/api/v1/accounting/investments/", {"name": "sanlam mmf"}, format="json").status_code == 400


def test_money_check_expects_less_in_the_till_once_money_is_invested(shop):
    client, org, *_ = shop
    mmf = _mmf(client)
    client.post("/api/v1/accounting/money-check/starting/", {"method": "MPESA", "amount": "80000", "idempotency_key": "start"}, format="json")
    assert _move(client, mmf, "DEPOSIT", "50000", "MPESA", "sweep").status_code == 201
    with organization_context(org):
        from apps.accounting.money_check import expected
        total, parts = expected("MPESA")
    assert total == D("30000") and parts["invested"] == D("-50000")
    spare = client.get("/api/v1/accounting/investments/").json()["spare_money"]
    assert D(next(p for p in spare if p["method"] == "MPESA")["expected"]) == D("30000")


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


def test_stock_is_paid_for_straight_from_the_mmf(shop):
    client, org, owner, _, store = shop
    mmf = _mmf(client)
    assert _move(client, mmf, "DEPOSIT", "50000", "MPESA", "sweep").status_code == 201
    receipt = _receive(org, owner, _stock(org, store), {"method": "INVESTMENT", "investment_id": mmf, "via": "MPESA", "amount": "20000"}, "INV-77")
    with organization_context(org):
        from apps.accounting.models import SupplierPurchase
        from apps.accounting.money_check import expected
        from apps.accounting.services import purchase_outstanding
        assert purchase_outstanding(SupplierPurchase.objects.get(receipt=receipt)) == 0
        assert expected("MPESA")[0] == D("-50000")  # the withdrawal landed in M-Pesa and went straight to the supplier
    row = client.get("/api/v1/accounting/investments/").json()["investments"][0]
    taken = row["movements"][0]
    assert (D(row["value"]), taken["kind"], taken["source"]) == (D("30000"), "WITHDRAWAL", "MPESA")
    assert taken["purchase"]["receipt_number"] == "INV-77" and taken["purchase"]["supplier"] == "Phone Hub"
    accounts, checks, pl = _books(org)
    assert accounts["1400"]["balance"] == D("30000") and accounts["2000"]["balance"] == D("0")
    assert next(c for c in checks if c["key"] == "investments")["reconciled"] and pl["net_profit_before_tax"] == D("0")


def test_stock_cannot_be_paid_from_the_mmf_beyond_its_value_or_by_a_cashier(shop):
    from rest_framework.exceptions import ValidationError
    client, org, owner, cashier, store = shop
    mmf = _mmf(client)
    _move(client, mmf, "DEPOSIT", "5000", "BANK", "in")
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
    _move(client, mmf, "DEPOSIT", "100000", "BANK", "in", occurred_on=str(start))
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
    _move(client, mmf, "WITHDRAWAL", "40000", "BANK", "out", occurred_on=str(next_month + timedelta(days=5)))
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
    _move(client, mmf, "DEPOSIT", "50000", "MPESA", "in")
    _move(client, other["id"], "DEPOSIT", "20000", "MPESA", "in-cic")
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
    _, checks, pl = _books(org)
    assert pl["net_profit_before_tax"] == D("410") and next(c for c in checks if c["key"] == "investments")["reconciled"]
    client.force_login(cashier)
    assert client.post(f"/api/v1/accounting/investments/{mmf}/monthly/", {"annual_rate": "1", "idempotency_key": "m-4"}, format="json").status_code == 403
    assert client.get("/api/v1/accounting/investments/reminder/").status_code == 403
