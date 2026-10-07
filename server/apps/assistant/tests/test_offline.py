"""Without an AI model the business assistant still understands the common questions and answers them exactly."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assistant import business_chat
from apps.assistant.offline import answer, period
from apps.assistant.tests.test_business_assistant import context, shop, staff  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def ask(ctx, question):
    with business_chat._scope(ctx):
        return answer(ctx, question)


def test_periods_are_read_from_the_question():
    today = timezone.localdate()
    assert period("sales today")[:2] == (today, today)
    assert period("profit this month")[:2] == (today.replace(day=1), today)
    assert period("trend over the last 90 days")[:2] == (today - timedelta(days=89), today)
    assert period("revenue last 2 weeks")[0] == today - timedelta(days=13)
    assert period("everything since we started")[0] == "beginning"
    last = today.replace(day=1) - timedelta(days=1)
    assert period("expenses last month")[:2] == (last.replace(day=1), last)


def test_the_common_questions_get_exact_answers(shop):  # noqa: F811
    ctx = context(shop)
    text, used = ask(ctx, "Give me a profit and loss summary for this month.")
    assert used == ["financial_summary"] and "Revenue: **KES 600**" in text
    text, used = ask(ctx, "How are my sales trending over the last 90 days?")
    assert used == ["sales_statistics"] and "Too early to call a trend" in text and "KES 600" in text
    text, used = ask(ctx, "What is running low and how much should I reorder?")
    assert used == ["stock_levels"]
    text, used = ask(ctx, "Which products bring in most of my revenue?")
    assert "Duka charger" in text and "KES 600" in text
    text, used = ask(ctx, "What do I owe suppliers?")
    assert used == ["money_business_owes"]
    text, used = ask(ctx, "How do I add a staff member?")
    assert used == ["platform_help"] and "staff" in text.lower()
    text, used = ask(ctx, "tell me a joke")
    assert "I can answer these without the AI assistant" in text


def test_a_role_without_access_is_told_so_not_shown(shop):  # noqa: F811
    cashier, _ = staff(shop, "CASHIER", "till-offline")
    text, used = ask(context(shop, cashier), "Give me a profit and loss summary for this month.")
    assert "Your role does not include this information" in text and used == []


def test_stock_and_single_product_questions_get_the_records_not_a_help_article(shop):  # noqa: F811
    ctx = context(shop)
    text, used = ask(ctx, "which items are in stock")
    assert used == ["stock_levels"] and "Duka charger: 8 available" in text
    text, used = ask(ctx, "Do I have duka charger?")
    assert used[0] == "find_products" and "8 available" in text and "sells at KES 300" in text
    text, used = ask(ctx, "how many chargers are left")
    assert "Duka charger" in text
    text, used = ask(ctx, "is the unicorn lamp in stock?")
    assert "couldn't find a product" in text
    text, used = ask(ctx, "How do I receive stock from a supplier?")
    assert used == ["platform_help"]
