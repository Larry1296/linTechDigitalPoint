"""The platform owner controls the public chat (switch, wording), its articles and the administrator's, and sees what
visitors asked. Nobody else can."""
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.assistant import claude
from apps.assistant.models import PublicQuestion
from apps.assistant.prompts import system_prompt
from apps.assistant.retrieval import admin_index, index, retrieve
from apps.assistant.tests.test_assistant import FakeStream, events, fake_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin():
    client = APIClient()
    client.force_authenticate(User.objects.create_user("platform-owner", password="Safe-pass-1848", is_superuser=True))
    return client


def ask(question):
    return APIClient().post("/api/v1/assistant/chat/", {"messages": [{"role": "user", "content": question}]}, format="json")


def test_only_the_platform_administrator_can_change_anything(admin):
    owner = APIClient()
    owner.force_authenticate(User.objects.create_user("shop-owner", password="Safe-pass-1848"))
    for client in (APIClient(), owner):
        assert client.get("/api/v1/assistant/admin/settings/").status_code in {401, 403}
        assert client.put("/api/v1/assistant/admin/articles/public/x/", {"title": "x", "body": "## q\na"}, format="json").status_code in {401, 403}
        assert client.get("/api/v1/assistant/admin/questions/").status_code in {401, 403}
    assert admin.get("/api/v1/assistant/admin/settings/").status_code == 200


def test_the_owner_switches_the_public_chat_off_and_sets_its_wording(admin, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    config = APIClient().get("/api/v1/assistant/config/").json()
    assert config["enabled"] and "How do I get started?" in config["suggestions"]
    saved = admin.put("/api/v1/assistant/admin/settings/", {"enabled": False, "greeting": "Karibu! Ask me anything.",
                                                            "suggestions": ["Do you work in Uganda?", " "]}, format="json").json()
    assert saved["enabled"] is False and saved["suggestions"] == ["Do you work in Uganda?"]
    config = APIClient().get("/api/v1/assistant/config/").json()
    assert config == {"enabled": False, "greeting": "Karibu! Ask me anything.", "suggestions": ["Do you work in Uganda?"]}
    assert ask("How do I start?").status_code == 503


def test_edited_hidden_and_added_articles_change_what_the_chat_answers_from(admin):
    before = system_prompt()
    listing = admin.get("/api/v1/assistant/admin/articles/public/").json()["articles"]
    mpesa = next(a for a in listing if a["slug"] == "08-mpesa")
    assert mpesa["source"] == "built-in" and mpesa["original"]["title"] == "M-Pesa"
    # A new article is searchable straight away, and the instructions list it.
    added = admin.put("/api/v1/assistant/admin/articles/public/delivery/", {"title": "Delivery",
                      "body": "## Do you deliver hardware?\nNo, we only provide the software."}, format="json")
    assert added.status_code == 200
    assert retrieve("deliver hardware")[0].heading == "Do you deliver hardware?"
    assert system_prompt() != before and "Do you deliver hardware?" in system_prompt()
    # Hiding a built-in article takes it out; restoring brings it back.
    admin.put("/api/v1/assistant/admin/articles/public/08-mpesa/", {**mpesa["original"], "active": False}, format="json")
    assert not any(p.article == "M-Pesa" for p in index().passages)
    restored = admin.delete("/api/v1/assistant/admin/articles/public/08-mpesa/").json()["articles"]
    assert next(a for a in restored if a["slug"] == "08-mpesa")["source"] == "built-in"
    assert any(p.article == "M-Pesa" for p in index().passages)
    # Administrator articles are edited the same way and never reach the public index.
    admin.put("/api/v1/assistant/admin/articles/admin/refunds/", {"title": "Refunds", "body": "## How do I refund a subscription?\nAsk finance."},
              format="json")
    assert admin_index().search("refund subscription")[0].heading == "How do I refund a subscription?"
    assert not any(p.article == "Refunds" for p in index().passages)
    bad = admin.put("/api/v1/assistant/admin/articles/public/oops/", {"title": "Oops", "body": "No questions here"}, format="json")
    assert bad.status_code == 400 and "##" in str(bad.json())


def test_visitor_questions_are_kept_so_gaps_can_be_filled(admin, settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    with mock.patch.object(claude, "client", return_value=fake_client(FakeStream(["Yes."]))):
        events(ask("Can I import my products from Excel?"))
        events(ask("zzqx blorf"))
    asked = admin.get("/api/v1/assistant/admin/questions/").json()
    assert asked["last_30_days"] == {"questions": 2, "unanswered": 1}
    gaps = admin.get("/api/v1/assistant/admin/questions/?unanswered=1").json()["questions"]
    assert [q["question"] for q in gaps] == ["zzqx blorf"]
    assert PublicQuestion.objects.filter(answered=True).get().articles
