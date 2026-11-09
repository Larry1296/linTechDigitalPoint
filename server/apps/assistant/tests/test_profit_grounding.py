"""Profit figures are worked out one way and checked before anyone sees them: the dashboard, the Reports summary, the
assistant without an AI and the AI's tool give the same figures for the same dates, every breakdown adds up, and an AI
answer quoting an amount the records do not hold is never shown."""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.utils import timezone

from apps.accounting.profit_report import ALL_TIME, reconcile_figures, report
from apps.assistant import business_chat, grounding
from apps.assistant.offline import answer
from apps.assistant.tests.test_business_assistant import (URL, FakeClaudeStream, call, claude_message, context, events,  # noqa: F401
                                                          keys, make_business, shop)
from apps.commerce.settlements import collect
from apps.inventory.services import complete_sale
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db
D = Decimal


def ask(ctx, question):
    with business_chat._scope(ctx):
        return answer(ctx, question)


def dashboard(business):
    response = business.client.get("/api/v1/inventory/dashboard/")
    assert response.status_code == 200, response.content
    return response.json()


def credit_sale(business, quantity=1, price=300):
    with organization_context(business.org):
        return complete_sale(lines=[{"variant": business.charger, "quantity": quantity, "unit_price": D(price)}], channel="POS",
                             number=f"CR-{timezone.now().timestamp()}", user=business.owner, paid_amount=0)


# The formula ---------------------------------------------------------------------------------------

def test_the_reported_example_does_not_add_up_without_its_adjustment():
    # Revenue 5,285, items' cost 3,076, gross 2,209, expenses 0, yet profit 2,784: KES 575 unexplained.
    problems = reconcile_figures(revenue=5285, cogs=3076, gross_profit=2209, expenses=0, profit=2784)
    assert [p["check"] for p in problems] == ["profit"] and problems[0]["difference"] == D("575.00")
    # The live records explained it: KES 575 of profit from earlier credit sales paid in these dates.
    assert reconcile_figures(revenue=5285, cogs=3076, gross_profit=2209, expenses=0, owed_profit=-575, profit=2784) == []
    assert reconcile_figures(revenue=5285, cogs=3076, gross_profit=2300, profit=2209)[0]["check"] == "gross_profit"


def test_an_empty_period_is_zero_and_adds_up(shop):  # noqa: F811
    with organization_context(shop.org):
        empty = report(timezone.localdate().replace(year=2001), timezone.localdate().replace(year=2001), ["SHOP"])
    assert empty["reconciled"] and empty["total"]["profit"] == 0 and empty["total"]["revenue"] == 0 and empty["records"]["lines"] == 0


# One set of figures everywhere -----------------------------------------------------------------------

def test_dashboard_reports_and_assistant_give_the_same_profit(shop):  # noqa: F811
    data = dashboard(shop)
    headline = D(str(data["owner_summary"]["all_time"]["profit"]))
    month = D(str(data["period_summary"]["profit"]))
    assert headline == month == D("280.00")  # 2 chargers at 300, bought at 160
    ctx = context(shop)
    explained, failed = call(ctx, "explain_profit", {})
    assert not failed and explained["report"]["reconciled"]
    lines = {line["field"]: D(str(line["amount"])) for line in explained["report"]["lines"]}
    assert lines["profit"] == headline and lines["revenue"] == D("600") and lines["cogs"] == D("320") and lines["gross_profit"] == D("280")
    books, _ = call(ctx, "financial_summary", {"start_date": "beginning"})
    assert D(str(books["totals"]["net_profit"])) == headline and books["reconciled"]
    text, used = ask(ctx, "How was the KES 280 profit on my dashboard reached?")
    assert used == ["explain_profit"] and "**KES 280.00 is the profit so far" in text and "Sales: **KES 600.00**" in text


def test_a_credit_payment_brings_its_profit_in_without_a_second_sale(shop):  # noqa: F811
    sale = credit_sale(shop)  # 300 on credit, cost 160: 140 profit owed
    ctx = context(shop)
    before, _ = call(ctx, "explain_profit", {})
    lines = {line["field"]: D(str(line["amount"])) for line in before["report"]["lines"]}
    assert (lines["revenue"], lines["owed_profit"], lines["profit"]) == (D("900"), D("140"), D("280"))
    with organization_context(shop.org):
        collect(sale=sale, amount=D("300"), method="CASH", key="paid-in-full")
    after, _ = call(ctx, "explain_profit", {})
    lines = {line["field"]: D(str(line["amount"])) for line in after["report"]["lines"]}
    # Revenue is not counted again: only the sale's profit comes in, as it is paid.
    assert (lines["revenue"], lines["owed_profit"], lines["profit"]) == (D("900"), D("0"), D("420"))
    assert after["report"]["reconciled"] and D(str(dashboard(shop)["owner_summary"]["all_time"]["profit"])) == D("420")


def test_owed_profit_is_traced_to_the_sale(shop):  # noqa: F811
    sale = credit_sale(shop)
    text, _ = ask(context(shop), "how was my dashboard profit reached")
    assert f"Sale {sale.number}: KES 140.00 still owed" in text and "Less profit still owed by customers" in text
    assert "add up exactly to the profit" in text


# A figure is explained only as itself ----------------------------------------------------------------

def test_a_figure_the_records_do_not_hold_is_said_so_never_replaced(shop):  # noqa: F811
    ctx = context(shop)
    data, failed = call(ctx, "explain_profit", {"figure": 7315})
    assert not failed and data["matched"] is False and "report" not in data
    assert any(row["value"] == 280 for row in data["nearest"])
    text, _ = ask(ctx, "How was the KES 7,315 profit displayed on my dashboard attained?")
    assert "**KES 7,315 cannot be matched**" in text and "I won't explain a different figure" in text
    assert "is the profit so far" not in text


def test_a_figure_is_matched_to_the_part_it_belongs_to(shop):  # noqa: F811
    data, _ = call(context(shop), "explain_profit", {"figure": "280"})
    assert data["matched"] and data["exact_value"] == 280 and data["report"]["reconciled"]


def test_a_report_that_does_not_add_up_is_flagged_and_logged_not_adjusted(shop, caplog):  # noqa: F811
    from apps.inventory import dashboard as books
    real = books.accrual_totals

    def broken(rows, units):
        result = real(rows, units)
        if units == ["SHOP"]:
            result["profit"] += D("10")  # a part whose profit is not its figures
        return result

    with mock.patch.object(books, "accrual_totals", broken), organization_context(shop.org):
        data = report(*ALL_TIME, ["SHOP"])
    assert data["reconciled"] is False and {p["check"] for p in data["checks"]} >= {"profit", "parts_add_up:profit"}
    assert data["total"]["profit"] == D("280.00")  # the whole is left as the books give it, not adjusted
    assert "Profit report does not add up" in caplog.text


# Each business sees only its own -------------------------------------------------------------------

def test_profit_reports_never_cross_businesses(shop):  # noqa: F811
    other = make_business("Kibanda", "KB-1")
    data, _ = call(context(other), "explain_profit", {})
    assert D(str(data["report"]["lines"][-1]["amount"])) == 0 and data["report"]["records"]["lines"] == 0
    found, _ = call(context(other), "explain_profit", {"figure": 280})
    assert found["matched"] is False


def test_a_role_without_profit_cannot_explain_it(shop):  # noqa: F811
    from apps.assistant.tests.test_business_assistant import staff
    cashier, _ = staff(shop, "CASHIER", "till-profit")
    data, failed = call(context(shop, cashier), "explain_profit", {})
    assert failed


# The AI is checked against the records ---------------------------------------------------------------

def test_the_number_check_accepts_record_figures_and_their_sums_only():
    results = [json.dumps({"lines": [{"amount": 15033.0}, {"amount": 8189.35}, {"amount": 6843.65}]})]
    assert grounding.unsupported("Sales **KES 15,033**, costs KES 8,189, gross KES 6,844.", results) == []
    assert grounding.unsupported("Together KES 23,222.35", results) == []  # two lines added up
    assert grounding.unsupported("Your profit is KES 2,784.", results) == [D("2784")]
    assert grounding.unsupported("Cash 300 in the drawer", []) == []  # a word ending in "sh" is not a currency


def _ai_answers(shop, question, text):  # noqa: F811
    tool = SimpleNamespace(type="tool_use", id="call-1", name="explain_profit", input={})
    fake = mock.MagicMock()
    fake.beta.messages.stream.side_effect = [FakeClaudeStream(claude_message("tool_use", tool), []),
                                             FakeClaudeStream(claude_message("end_turn", SimpleNamespace(type="text", text=text)), [text])]
    with mock.patch.object(business_chat, "_anthropic", return_value=fake):
        stream = events(shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": question}]}, format="json"))
    return "".join(e.get("text", "") for e in stream if e["type"] == "text"), stream


def test_an_ai_answer_with_figures_from_the_records_is_shown(shop):  # noqa: F811
    text, stream = _ai_answers(shop, "How was my profit reached?", "Sales KES 600 less the items' cost KES 320 gives **KES 280**.")
    assert text == "Sales KES 600 less the items' cost KES 320 gives **KES 280**." and stream[-1]["type"] == "done"


def test_an_ai_answer_with_a_made_up_total_is_replaced_by_the_records(shop, caplog):  # noqa: F811
    text, _ = _ai_answers(shop, "How was the profit on my dashboard reached?", "Your profit is **KES 2,784**: sales KES 5,285.")
    assert "2,784" not in text and "5,285" not in text
    assert "**KES 280.00 is your profit so far**" in text and "AI" not in text  # the business is not told about the AI
    assert "answer rejected" in caplog.text


def test_when_the_ai_fails_the_profit_comes_from_the_records(shop):  # noqa: F811
    import anthropic
    fake = mock.MagicMock()
    fake.beta.messages.stream.side_effect = anthropic.APIConnectionError(request=mock.MagicMock())
    with mock.patch.object(business_chat, "_anthropic", return_value=fake):
        stream = events(shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "How was the KES 280 profit reached?"}]},
                                         format="json"))
    text = "".join(e.get("text", "") for e in stream if e["type"] == "text")
    assert "**KES 280.00 is the profit so far" in text and "Gross profit: KES 280.00" in text


def test_a_day_without_sales_still_shows_money_paid_on_earlier_sales(shop):  # noqa: F811
    # 9 Nov 2026 (live): a customer paid 250 cash on an earlier credit sale; the assistant said nothing came into the drawer.
    sale = credit_sale(shop)
    with organization_context(shop.org):
        from apps.commerce.models import Sale
        from apps.commerce.models import Payment
        earlier = timezone.now() - timezone.timedelta(days=5)
        Sale.objects.exclude(pk=sale.pk).update(created_at=earlier)
        Payment.objects.exclude(sale=sale).update(created_at=earlier)  # paid in full when it was sold
        Sale.objects.filter(pk=sale.pk).update(created_at=timezone.now() - timezone.timedelta(days=3))
        collect(sale=sale, amount=D("250"), method="CASH", key="part-paid")
    ctx = context(shop)
    today = timezone.localdate().isoformat()
    data, _ = call(ctx, "sales_summary", {"start_date": today, "end_date": today})
    assert data["totals"]["sales_count"] == 0
    earlier = data["paid_on_earlier_sales"]
    assert (earlier["count"], earlier["amount"]) == (1, 250.0) and earlier["by_method"] == [{"method": "CASH", "payments": 1, "amount": 250.0}]
    assert earlier["payments"][0]["sale_number"] == sale.number
    text, _ = ask(ctx, "sales today")
    assert "No new sales today" in text and "Paid on earlier credit sales: **KES 250**" in text and "not new sales" in text
    # Over the days the sale was made in, its own payment is part of that sale, not an earlier one.
    week, _ = call(ctx, "sales_summary", {"start_date": (timezone.localdate() - timezone.timedelta(days=4)).isoformat()})
    assert week["paid_on_earlier_sales"]["count"] == 0
