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
    platform = {"platform_overview", "platform_businesses", "platform_admin_help"}
    assert tools == set(business_tools.TOOLS) - platform  # an owner gets every business tool, not the platform administrator's
    for name in tools:
        args = {"find_products": {"query": "charger"}, "platform_help": {"question": "How do I import products?"},
                "find_sales": {"customer": "nobody"}}.get(name, {})
        result, failed = call(ctx, name, args)
        assert not failed, (name, result)
    products, _ = call(ctx, "find_products", {"query": "CHG-1"})
    assert products["products"][0]["on_hand"] == 8 and products["products"][0]["average_unit_cost"] == 160
    sales, _ = call(ctx, "sales_summary", {"group_by": "product"})
    assert sales["totals"]["sales_count"] == 1 and sales["totals"]["sales_value"] == 600 and sales["totals"]["gross_profit"] == 280
    assert sales["rows"] == [{"product": "Duka charger", "value": 600.0, "units_sold": 2.0, "gross_profit": 280.0}]
    stock, _ = call(ctx, "inventory_analysis", {"days": 30})
    top = stock["top_sellers"][0]
    # The business was created today: averages per day count only the days it has existed.
    assert top["abc_class"] == "A" and top["sell_through_pct"] == 20 and top["days_of_cover"] == 4 and stock["period_days"] == 1
    low, _ = call(ctx, "stock_levels", {"view": "all"})
    assert low["summary"]["units_on_hand"] == 8 and low["items"][0]["suggested_reorder"] == 12
    stats, _ = call(ctx, "sales_statistics", {"start_date": (timezone.localdate() - timedelta(days=13)).isoformat()})
    assert stats["statistics"]["total"] == 600 and stats["statistics"]["days"] == 1 and stats["records_start"]
    assert stats["statistics"]["trend"]["strength"] == "too few days to tell"


def test_the_assistant_sees_money_owed_where_it_is_and_single_sales_since_the_start(shop):
    ctx = context(shop)
    whole, _ = call(ctx, "sales_summary", {"start_date": "beginning"})
    assert whole["period"]["start"] == timezone.localtime(shop.org.created_at).date().isoformat() and whole["totals"]["sales_count"] == 1
    with organization_context(shop.org):
        from apps.commerce.models import Sale
        number = Sale.objects.get().number
    found, _ = call(ctx, "find_sales", {"sale_number": number.lower()})
    assert found["matches"] == 1 and found["sales"][0]["items"][0]["quantity"] == 2 and found["sales"][0]["gross_profit"] == 280
    owes, _ = call(ctx, "money_business_owes")
    bought, _ = call(ctx, "purchases_and_suppliers")
    assert bought["total_bought"] == 1600 and bought["by_supplier"][0]["supplier"] == "Supplier"
    assert owes["suppliers_total"] == bought["by_supplier"][0]["still_owed"]
    money, _ = call(ctx, "money_position")
    assert money["net_worth"] == money["owns"] - money["owes"] and "Stock on the shelves (at cost)" in [g["label"] for g in money["groups"]]
    owed, _ = call(ctx, "money_owed_to_business")
    assert owed["customers_owe_total"] == 0 and owed["money_lent_out"]["loans"] == []
    log, _ = call(ctx, "activity_log", {"start_date": "beginning"})
    assert log["total_actions"] > 0
    # A cashier sees sales, not the books, what is owed or the audit trail.
    cashier, _ = staff(shop, "CASHIER", "till-2")
    tools = offered(context(shop, cashier))
    assert {"find_sales", "top_customers"} <= tools
    assert {"money_position", "money_owed_to_business", "money_business_owes", "activity_log", "investments"}.isdisjoint(tools)


def test_the_assistant_sees_each_mpesa_transaction_and_service_job_in_full(shop):
    from apps.cyber.models import CyberServiceProfile
    from apps.cyber.services import complete_job, create_job
    from apps.mpesa.models import MpesaOutlet
    from apps.mpesa.services import open_session, post_transaction, reverse_transaction
    with organization_context(shop.org):
        outlet = MpesaOutlet.objects.create(store=Store.objects.first(), display_name="Main M-Pesa")
        session = open_session(outlet=outlet, operator=shop.owner, opening_cash="5000", opening_float="8000")
        post_transaction(session=session, transaction_type="CUSTOMER_DEPOSIT", transaction_amount="1200", user=shop.owner, idempotency_key="d-1",
                         provider_reference="QWE123RTY", customer_name="Jane Wanjiru", customer_phone="0712345678", customer_id_number="12345678")
        wrong, _ = post_transaction(session=session, transaction_type="CUSTOMER_WITHDRAWAL", transaction_amount="700", user=shop.owner,
                                    idempotency_key="w-1", provider_reference="ASD456FGH", customer_name="Ali Hassan",
                                    customer_phone="0722000111", customer_id_number="87654321")
        reverse_transaction(original=wrong, user=shop.owner, idempotency_key="r-1", reason="Wrong number")
        lamination = ProductVariant.objects.create(product=Product.objects.create(name="Lamination", slug="lamination", product_type="SERVICE",
                                                                                  category=Category.objects.first()), sku="LAM-1", selling_price=50)
        CyberServiceProfile.objects.create(variant=lamination, billing_unit="FIXED")
        job = create_job(user=shop.owner, lines=[{"variant_id": lamination.pk, "quantity": 1}], walk_in_customer_name="Peter", phone="0733000222")
        complete_job(job=job, user=shop.owner, payment_method="CASH")
    ctx = context(shop)
    mpesa, failed = call(ctx, "mpesa_summary", {"start_date": timezone.localdate().isoformat()})
    assert not failed, mpesa
    shift = mpesa["shifts"][0]
    assert shift["status"] == "OPEN" and shift["opening_cash"] == 5000 and shift["cash_now"] == 6200 and shift["float_now"] == 6800
    latest = mpesa["latest_transactions"]
    assert [t["type"] for t in latest] == ["REVERSAL", "CUSTOMER_WITHDRAWAL", "CUSTOMER_DEPOSIT"]
    assert latest[1]["reversed"] and latest[0]["reverses"] == wrong.internal_reference
    deposit = latest[2]
    assert deposit["amount"] == 1200 and deposit["customer"] == "Jane Wanjiru" and deposit["phone"].endswith("712345678")
    assert deposit["mpesa_code"] == "QWE123RTY" and "12345678" not in json.dumps(mpesa).replace("712345678", "")
    jobs, failed = call(ctx, "service_jobs", {"start_date": timezone.localdate().isoformat()})
    assert not failed, jobs
    listed = jobs["jobs"][0]
    assert listed["customer"] == "Peter" and listed["phone"] == "0733000222" and listed["total"] == 50
    assert listed["services"][0]["service"].startswith("Lamination") and listed["paid_by"] == [{"method": "CASH", "amount": 50.0}]
    assert listed["minutes_to_complete"] is not None and jobs["average_minutes_to_complete"] is not None
    from apps.assistant import offline
    with business_chat._scope(ctx):
        text, _ = offline.answer(ctx, "is the last transaction in this shift a withdrawal or deposit")
    assert "Open shift" in text and "KES 6,200" in text and "Jane Wanjiru 0712345678" in text and "Customer Withdrawal (reversed)" in text


def test_the_platform_administrator_also_sees_every_business_in_general_terms_only(shop):
    other = make_business("Rival", "RIVAL-1")
    sold = other.client.post("/api/v1/commerce/pos/complete/", {"items": [{"variant_id": other.charger.pk, "quantity": 1}]}, format="json")
    assert sold.status_code == 201, sold.content
    shop.owner.is_superuser = True
    shop.owner.save(update_fields=["is_superuser"])
    ctx = context(shop)
    assert {"platform_overview", "platform_businesses", "platform_admin_help"} <= offered(ctx)
    overview, failed = call(ctx, "platform_overview")
    assert not failed and overview["summary"]["businesses"] == Organization.objects.count()
    listed, _ = call(ctx, "platform_businesses", {"query": "rival"})
    rival = listed["businesses"][0]
    assert listed["matching"] == 1 and rival["business"] == "Rival" and rival["sales_last_30_days"] == 1
    assert not {"sales_value", "revenue", "customers", "stock"} & set(rival)  # activity counts, never the business's money
    guide, _ = call(ctx, "platform_admin_help", {"question": "How do I record a payment received outside the app?"})
    assert guide["passages"][0]["section"] == "How do I record a payment received outside the app?"
    with business_chat._scope(ctx):
        assert "platform administrator" in business_chat.business_prompt(ctx)
    # The public help chat never gets the administrator's articles.
    from apps.assistant.retrieval import index
    assert not any(p.article == "Running the platform" for p in index().passages)


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
    def __init__(self, message, texts, events=None):
        self.message = message
        self.events = events if events is not None else [SimpleNamespace(type="text", text=text) for text in texts]

    def __iter__(self):
        return iter(self.events)

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
    assert "Duka" in first["system"][0]["text"] and {t["name"] for t in first["tools"]} == set(business_tools.TOOLS) - {"platform_overview", "platform_businesses", "platform_admin_help"} | {"web_search"}


def test_claude_compares_prices_with_kenyan_shops_and_resumes_a_paused_search(shop):
    search = SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="server_tool_use", name="web_search"))
    text = lambda value: SimpleNamespace(type="text", text=value)
    paused = claude_message("pause_turn", SimpleNamespace(type="text", text="Checking."), SimpleNamespace(type="server_tool_use", name="web_search"))
    fake = mock.MagicMock()
    fake.beta.messages.stream.side_effect = [
        FakeClaudeStream(paused, [], [text("Checking."), search]),
        FakeClaudeStream(claude_message("end_turn", SimpleNamespace(type="text", text="Jiji sells it for KES 299.")), [], [text("Jiji sells it for KES 299.")]),
    ]
    with mock.patch.object(business_chat, "_anthropic", return_value=fake):
        got = events(shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "Are my extensions overpriced?"}]}, format="json"))
    assert {"type": "tool", "name": "web_search", "label": "Checking other shops' prices"} in got
    assert "".join(e.get("text", "") for e in got) == "Checking.\n\nJiji sells it for KES 299."
    first, second = (call.kwargs for call in fake.beta.messages.stream.call_args_list)
    web = next(t for t in first["tools"] if t["name"] == "web_search")
    assert web["type"] == "web_search_20260209" and "jiji.co.ke" in web["allowed_domains"] and web["user_location"] == {"type": "approximate", "timezone": "Africa/Nairobi"}
    assert "Other shops' prices" in first["system"][0]["text"]
    # The paused turn is sent back as it was, with no extra message, so the search carries on.
    assert second["messages"][-1] == {"role": "assistant", "content": paused.content}


def test_market_search_can_be_turned_off_and_is_never_offered_to_chatgpt(shop, settings):
    settings.BUSINESS_ASSISTANT_WEB_SEARCH = False
    assert business_chat.web_search_on("anthropic") is False
    settings.BUSINESS_ASSISTANT_WEB_SEARCH = True
    assert business_chat.web_search_on("anthropic") is True and business_chat.web_search_on("openai") is False


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
        response = shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": "How much did I sell today?"}]}, format="json")
        stream = events(response)
    # Without any AI key the common questions are still answered, exactly, from the records.
    assert response.status_code == 200 and {"type": "tool", "name": "sales_summary", "label": "Checking sales"} in stream
    text = "".join(e["text"] for e in stream if e["type"] == "text")
    assert "1 sale worth KES 600" in text and "Answered directly from your records" in text


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


def test_an_ai_account_out_of_credit_is_named_to_the_platform_owner_and_a_price_comparison_is_not_misread(shop):
    import anthropic
    no_credit = anthropic.BadRequestError("Your credit balance is too low to access the Anthropic API.",
                                          response=mock.MagicMock(status_code=400, headers={}), body=None)
    fake = mock.MagicMock()
    fake.beta.messages.stream.side_effect = no_credit
    question = ("Compare all the current products SP with numerous local retailers in Nairobi; if you notice a significant "
                "difference point it out clearly so that I correct")
    ask = lambda: "".join(e.get("text", "") for e in events(shop.client.post(URL + "chat/", {"messages": [{"role": "user", "content": question}]}, format="json")))
    with mock.patch.object(business_chat, "_anthropic", return_value=fake):
        owner_sees = ask()
        shop.owner.is_superuser = True
        shop.owner.save()
        platform_sees = ask()
    assert "unavailable right now" in owner_sees and "credit" not in owner_sees
    assert "run out of credit" in platform_sees and "console.anthropic.com" in platform_sees
    for text in (owner_sees, platform_sees):
        assert "Comparing your prices with other shops needs the AI assistant" in text and "No stock items found" not in text
