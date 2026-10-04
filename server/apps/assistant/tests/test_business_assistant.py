"""Each business's own assistant: exact statistics, read-only tools scoped to one business and role, and both providers."""
import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.assistant import analytics, business_chat, business_tools
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.models import Store
from apps.inventory.services import complete_stock_receipt
from apps.tenancy.context import organization_context
from apps.tenancy.models import Membership, Organization, OrganizationSubscription

pytestmark = pytest.mark.django_db
URL = "/api/v1/business-assistant/"


@pytest.fixture(autouse=True)
def keys(settings):
    cache.clear()
    settings.ANTHROPIC_API_KEY = "test-anthropic"
    settings.OPENAI_API_KEY = "test-openai"
    settings.BUSINESS_ASSISTANT_PROVIDER = "anthropic"
    business_chat._clients.clear()
    yield
    business_chat._clients.clear()


def make_business(name, sku):
    owner = User.objects.create_user(f"{name.lower()}-owner", password="Safe-pass-1848", first_name=name)
    org = Organization.objects.create(name=name, slug=name.lower(), owner=owner, currency="KES")
    Membership.objects.create(user=owner, organization=org, role="OWNER")
    OrganizationSubscription.objects.create(organization=org, status="ACTIVE")
    with organization_context(org):
        Store.objects.create(name="Main")
        category = Category.objects.create(name="Chargers", slug="chargers")
        charger = ProductVariant.objects.create(product=Product.objects.create(name=f"{name} charger", slug="charger", category=category),
                                                name="Standard", sku=sku, selling_price=300, minimum_stock=3, target_stock=20)
        complete_stock_receipt(supplier_name="Supplier", external_reference="INV-1", received_at=timezone.now() - timedelta(hours=1),
                               lines=[{"variant_id": charger.pk, "received_quantity": "10", "unit_cost": "160"}], user=owner)
    client = APIClient()
    client.force_authenticate(owner)
    return SimpleNamespace(owner=owner, org=org, charger=charger, client=client)


@pytest.fixture
def shop():
    business = make_business("Duka", "CHG-1")
    sold = business.client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": business.charger.pk, "quantity": 2}]}, format="json")
    assert sold.status_code == 201, sold.content
    return business


def staff(business, role, username):
    user = User.objects.create_user(username, password="Safe-pass-1848")
    Membership.objects.create(user=user, organization=business.org, role=role)
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def context(business, user=None):
    with organization_context(business.org):
        store = Store.objects.first()
        ctx = business_tools.Context(user or business.owner, business.org, store)
    return ctx


def offered(ctx):
    with business_chat._scope(ctx):
        return {name for name, _, _ in business_tools.available(ctx)}


def call(ctx, name, args=None):
    with business_chat._scope(ctx):
        text, failed = business_tools.run(ctx, name, args or {})
    return json.loads(text) if not text.endswith("period)") else text, failed


def events(response):
    body = b"".join(response.streaming_content).decode()
    return [json.loads(line[6:]) for line in body.split("\n\n") if line.startswith("data: ")]


# Statistics --------------------------------------------------------------------------------------

def test_trend_fits_a_straight_line_exactly():
    trend = analytics.linear_trend([10, 12, 14, 16, 18])
    assert round(trend["slope_per_day"], 6) == 2 and round(trend["intercept"], 6) == 10 and round(trend["r_squared"], 6) == 1


def test_series_statistics_flag_unusual_days_and_forecast_the_trend():
    start = date(2026, 9, 1)
    values = {start + timedelta(days=i): 100 for i in range(20)}
    values[start + timedelta(days=10)] = 400
    stats = analytics.describe_series(analytics.daily_series(values, start, start + timedelta(days=19)), forecast_days=3)
    assert stats["days"] == 20 and stats["total"] == 2300 and stats["median_per_day"] == 100
    assert [d["date"] for d in stats["unusual_days"]] == ["2026-09-11"] and stats["unusual_days"][0]["kind"] == "unusually high"
    assert len(stats["forecast_next_days"]) == 3 and stats["forecast_next_days"][0]["date"] == "2026-09-21"
    assert all(d["low"] <= d["expected"] <= d["high"] for d in stats["forecast_next_days"])


def test_abc_classes_follow_the_pareto_cut_offs():
    rows = analytics.abc_classes([{"sku": s, "revenue": v} for s, v in [("a", 700), ("b", 150), ("c", 100), ("d", 50)]])
    assert [(row["sku"], row["abc_class"]) for row in rows] == [("a", "A"), ("b", "A"), ("c", "B"), ("d", "C")]


# Tools -------------------------------------------------------------------------------------------

def test_every_tool_answers_from_the_business_records(shop):
    ctx = context(shop)
    tools = offered(ctx)
    assert tools == set(business_tools.TOOLS)  # an owner gets every tool for the enabled modules
    for name in tools:
        args = {"find_products": {"query": "charger"}, "platform_help": {"question": "How do I import products?"}}.get(name, {})
        result, failed = call(ctx, name, args)
        assert not failed, (name, result)
    products, _ = call(ctx, "find_products", {"query": "CHG-1"})
    assert products["products"][0]["on_hand"] == 8 and products["products"][0]["average_unit_cost"] == 160
    sales, _ = call(ctx, "sales_summary", {"group_by": "product"})
    assert sales["totals"]["sales_count"] == 1 and sales["totals"]["sales_value"] == 600 and sales["totals"]["gross_profit"] == 280
    assert sales["rows"] == [{"product": "Duka charger", "value": 600.0, "units_sold": 2.0, "gross_profit": 280.0}]
    stock, _ = call(ctx, "inventory_analysis", {"days": 30})
    top = stock["top_sellers"][0]
    assert top["abc_class"] == "A" and top["sell_through_pct"] == 20 and top["days_of_cover"] == 120
    low, _ = call(ctx, "stock_levels", {"view": "all"})
    assert low["summary"]["units_on_hand"] == 8 and low["items"][0]["suggested_reorder"] == 12
    stats, _ = call(ctx, "sales_statistics", {"start_date": (timezone.localdate() - timedelta(days=13)).isoformat()})
    assert stats["statistics"]["total"] == 600 and stats["statistics"]["days"] == 14


def test_bad_tool_input_is_reported_back_to_the_model(shop):
    ctx = context(shop)
    result, failed = call(ctx, "sales_summary", {"start_date": "last week"})
    assert failed and "YYYY-MM-DD" in result["error"]
    result, failed = call(ctx, "sales_summary", {"start_date": "2026-09-10", "end_date": "2026-09-01"})
    assert failed and "on or before" in result["error"]
    result, failed = call(ctx, "delete_everything")
    assert failed and "not available" in result["error"]


def test_a_cashier_gets_no_profit_costs_or_books(shop):
    cashier, _ = staff(shop, "CASHIER", "till")
    ctx = context(shop, cashier)
    tools = offered(ctx)
    assert {"financial_summary", "expense_analysis", "inventory_analysis", "stock_levels"}.isdisjoint(tools)
    assert {"find_products", "sales_summary", "platform_help"} <= tools
    result, failed = call(ctx, "financial_summary")
    assert failed and "not available" in result["error"]
    sales, _ = call(ctx, "sales_summary")
    assert "gross_profit" not in sales["totals"] and "cost_of_goods" not in sales["totals"]
    product, _ = call(ctx, "find_products", {"query": "CHG-1"})
    assert "average_unit_cost" not in product["products"][0] and "on_hand" not in product["products"][0]
    result, failed = call(ctx, "sales_statistics", {"metric": "gross_profit"})
    assert failed and "cannot see profit" in result["error"]
    with business_chat._scope(ctx):
        prompt = business_chat.business_prompt(ctx)
    assert "does not allow buying costs or profit" in prompt and "financial summary" in prompt


def test_one_business_never_sees_another(shop):
    other = make_business("Rival", "RIVAL-1")
    ctx = context(shop)
    found, _ = call(ctx, "find_products", {"query": "charger"})
    assert [p["sku"] for p in found["products"]] == ["CHG-1"]
    theirs, _ = call(context(other), "sales_summary")
    assert theirs["totals"]["sales_count"] == 0


# Chat endpoint -----------------------------------------------------------------------------------

class FakeClaudeStream:
    def __init__(self, message, texts):
        self.message, self.text_stream = message, iter(texts)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_final_message(self):
        return self.message


def claude_message(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks),
                           usage=SimpleNamespace(input_tokens=1000, cache_read_input_tokens=800, output_tokens=50))


def test_claude_looks_up_the_data_then_answers(shop):
    tool = SimpleNamespace(type="tool_use", id="call-1", name="sales_summary", input={"group_by": "product"})
    fake = mock.MagicMock()
    fake.beta.messages.stream.side_effect = [
        FakeClaudeStream(claude_message("tool_use", SimpleNamespace(type="text", text="Let me check."), tool), ["Let me check."]),
        FakeClaudeStream(claude_message("end_turn", SimpleNamespace(type="text", text="You sold 2 chargers.")), ["You sold 2 chargers."]),
    ]
    with mock.patch.object(business_chat, "_anthropic", return_value=fake):
        response = shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "What sold this month?"}]}, format="json")
        got = events(response)
    assert response.status_code == 200
    assert [e["type"] for e in got] == ["text", "tool", "text", "text", "done"]
    assert got[1]["label"] == "Checking sales" and "".join(e.get("text", "") for e in got) == "Let me check.\n\nYou sold 2 chargers."
    second = fake.beta.messages.stream.call_args_list[1].kwargs
    result = second["messages"][-1]["content"][0]
    # The tool ran after the view returned, still inside this business: it found this business's sale.
    assert result["tool_use_id"] == "call-1" and '"sales_value": 600.0' in result["content"] and "is_error" not in result
    first = fake.beta.messages.stream.call_args_list[0].kwargs
    assert first["model"] == "claude-opus-5-5" and first["thinking"] == {"type": "adaptive"} and first["fallbacks"] == "default"
    assert "Duka" in first["system"][0]["text"] and {t["name"] for t in first["tools"]} == set(business_tools.TOOLS)


def test_claude_refusal_is_shown_and_no_tools_run(shop):
    fake = mock.MagicMock()
    fake.beta.messages.stream.return_value = FakeClaudeStream(claude_message("refusal"), [])
    with mock.patch.object(business_chat, "_anthropic", return_value=fake), mock.patch.object(business_tools, "run") as run:
        got = events(shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "hi"}]}, format="json"))
    assert got[0]["type"] == "refusal" and not run.called


def openai_chunk(content=None, tool_calls=None, finish=None, usage=None):
    delta = SimpleNamespace(content=content, refusal=None, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)] if usage is None else [], usage=usage)


def test_openai_looks_up_the_data_then_answers(shop):
    shop.org.settings = {"assistant": {"provider": "openai"}}
    shop.org.save()
    part = lambda **kw: SimpleNamespace(index=0, id=kw.get("id"), type="function", function=SimpleNamespace(name=kw.get("name"), arguments=kw.get("arguments")))
    usage = SimpleNamespace(prompt_tokens=900, completion_tokens=40, prompt_tokens_details=SimpleNamespace(cached_tokens=0))
    fake = mock.MagicMock()
    fake.chat.completions.create.side_effect = [
        iter([openai_chunk(tool_calls=[part(id="c1", name="stock_levels", arguments='{"view"')]),
              openai_chunk(tool_calls=[part(arguments=': "all"}')]), openai_chunk(finish="tool_calls"), openai_chunk(usage=usage)]),
        iter([openai_chunk(content="You have 8 chargers."), openai_chunk(finish="stop"), openai_chunk(usage=usage)]),
    ]
    with mock.patch.object(business_chat, "_openai", return_value=fake):
        got = events(shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "How many chargers?"}]}, format="json"))
    assert [e["type"] for e in got] == ["tool", "text", "done"] and got[1]["text"] == "You have 8 chargers."
    second = fake.chat.completions.create.call_args_list[1].kwargs
    assistant, tool_result = second["messages"][-2:]
    assert assistant["tool_calls"][0]["function"] == {"name": "stock_levels", "arguments": '{"view": "all"}'}
    assert tool_result["tool_call_id"] == "c1" and '"units_on_hand": 8.0' in tool_result["content"]
    first = fake.chat.completions.create.call_args_list[0].kwargs
    assert first["model"] == "gpt-5.5" and first["messages"][0]["role"] == "system" and first["tool_choice"] == "auto"


def test_the_last_round_must_answer_without_more_tools(shop, monkeypatch):
    monkeypatch.setattr(business_chat, "MAX_ROUNDS", 2)
    tool = SimpleNamespace(type="tool_use", id="c", name="business_overview", input={})
    fake = mock.MagicMock()
    fake.beta.messages.stream.side_effect = [FakeClaudeStream(claude_message("tool_use", tool), []),
                                             FakeClaudeStream(claude_message("end_turn", SimpleNamespace(type="text", text="Done")), ["Done"])]
    with mock.patch.object(business_chat, "_anthropic", return_value=fake):
        events(shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "Tell me everything"}]}, format="json"))
    assert [c.kwargs["tool_choice"] for c in fake.beta.messages.stream.call_args_list] == [{"type": "auto"}, {"type": "none"}]


def test_chat_needs_a_business_member_and_a_configured_provider(shop, settings):
    assert APIClient().post(URL + "chat/", {"messages": [{"role": "user", "content": "hi"}]}, format="json").status_code == 403
    settings.ANTHROPIC_API_KEY = settings.OPENAI_API_KEY = ""
    with mock.patch.dict("os.environ", {}, clear=True):
        response = shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "hi"}]}, format="json")
    assert response.status_code == 503


def test_owner_chooses_the_provider_and_staff_cannot(shop, settings):
    data = shop.client.get(URL + "settings/").json()
    assert data["provider"] == "anthropic" and data["can_manage"] is True
    assert {p["id"] for p in data["providers"]} == {"anthropic", "openai"}
    assert shop.client.put(URL + "settings/", {"provider": "openai"}, format="json").json()["provider"] == "openai"
    assert shop.client.put(URL + "settings/", {"provider": "gemini"}, format="json").status_code == 400
    _, cashier = staff(shop, "CASHIER", "till")
    assert cashier.get(URL + "settings/").json() == {**data, "provider": "openai", "can_manage": False}
    assert cashier.put(URL + "settings/", {"provider": "anthropic"}, format="json").status_code == 403
    settings.OPENAI_API_KEY = ""
    with mock.patch.dict("os.environ", {}, clear=True):
        assert shop.client.get(URL + "settings/").json()["provider"] == "anthropic"  # falls back to a provider that works
