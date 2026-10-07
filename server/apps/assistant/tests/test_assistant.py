import json
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.assistant import claude
from apps.assistant.prompts import question_turn, system_prompt
from apps.assistant.retrieval import load_passages, retrieve
from apps.assistant.tests.retrieval_cases import CASES

URL = "/api/v1/assistant/chat/"


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()
    yield
    cache.clear()


def events(response):
    body = b"".join(response.streaming_content).decode()
    return [json.loads(line[6:]) for line in body.split("\n\n") if line.startswith("data: ")]


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.text_stream = iter(chunks)
        self.final = SimpleNamespace(stop_reason=stop_reason, usage=SimpleNamespace(input_tokens=900, cache_read_input_tokens=1200, output_tokens=40))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_final_message(self):
        return self.final


def fake_client(stream):
    fake = mock.MagicMock()
    fake.beta.messages.stream.return_value = stream
    return fake


@pytest.mark.django_db
def test_every_customer_question_finds_its_help_section():
    for question, heading in CASES:
        headings = [p.heading.lower() for p in retrieve(question)[:5]]
        assert any(heading.lower() in h for h in headings), (question, headings)


@pytest.mark.django_db
def test_knowledge_base_fills_in_the_platform_name_and_has_no_placeholders(settings):
    settings.PLATFORM_NAME = "DukaFlow"
    passages = load_passages()
    assert len(passages) > 40
    assert not any("{platform}" in p.text or "{contact}" in p.text or "{platform}" in p.heading for p in passages)


@pytest.mark.django_db
def test_system_prompt_is_stable_and_questions_carry_their_passages():
    assert system_prompt() == system_prompt()
    turn = question_turn("How much is it?", retrieve("How much is it?"))
    assert turn.startswith("<passages>") and "<question>\nHow much is it?\n</question>" in turn


@pytest.mark.django_db
@pytest.mark.parametrize("body, message", [
    ({}, "list of messages"),
    ({"messages": [{"role": "robot", "content": "hi"}]}, "role"),
    ({"messages": [{"role": "user", "content": "x" * 1001}]}, "at most 1000"),
    ({"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}, "last message"),
])
def test_rejects_malformed_conversations(body, message):
    response = APIClient().post(URL, body, format="json")
    assert response.status_code == 400 and message in response.json()["detail"]


@pytest.mark.django_db
def test_answers_from_the_help_articles_without_an_api_key(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = ""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    response = APIClient().post(URL, {"messages": [{"role": "user", "content": "Can I import my products from Excel?"}]}, format="json")
    stream = events(response)
    assert response.status_code == 200 and "import" in stream[0]["text"].lower() and stream[-1] == {"type": "done"}
    nonsense = events(APIClient().post(URL, {"messages": [{"role": "user", "content": "zzqx blorf wibble"}]}, format="json"))
    assert "couldn't find that" in nonsense[0]["text"]


@pytest.mark.django_db
def test_streams_an_answer_to_an_anonymous_visitor_with_cached_instructions(settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    settings.ASSISTANT_MODEL = "claude-opus-5-5"
    fake = fake_client(FakeStream(["Create an ", "account first."]))
    with mock.patch.object(claude, "client", return_value=fake):
        response = APIClient().post(URL, {"messages": [
            {"role": "user", "content": "What is DukaFlow?"},
            {"role": "assistant", "content": "A business management platform."},
            {"role": "user", "content": "How do I get started?"},
        ]}, format="json")
        stream = events(response)
    assert response.status_code == 200 and response["Content-Type"] == "text/event-stream"
    assert "".join(e["text"] for e in stream if e["type"] == "text") == "Create an account first."
    assert stream[-1] == {"type": "done"} and "Getting started" in stream[-2]["items"]
    kwargs = fake.beta.messages.stream.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["fallbacks"] == "default"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    # History is passed through; only the new question carries retrieved passages.
    assert kwargs["messages"][0] == {"role": "user", "content": "What is DukaFlow?"}
    assert "<passages>" in kwargs["messages"][-1]["content"] and "How do I get started?" in kwargs["messages"][-1]["content"]


@pytest.mark.django_db
def test_a_refusal_or_api_failure_becomes_a_friendly_event(settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    body = {"messages": [{"role": "user", "content": "Tell me something"}]}
    with mock.patch.object(claude, "client", return_value=fake_client(FakeStream([], stop_reason="refusal"))):
        assert events(APIClient().post(URL, body, format="json"))[-1]["type"] == "refusal"
    failing = mock.MagicMock()
    failing.beta.messages.stream.side_effect = claude.anthropic.APIConnectionError(request=mock.MagicMock())
    with mock.patch.object(claude, "client", return_value=failing):
        assert events(APIClient().post(URL, body, format="json"))[-1]["type"] == "error"


@pytest.mark.django_db
def test_visitors_are_rate_limited(settings):
    settings.ANTHROPIC_API_KEY = "test-key"
    body = {"messages": [{"role": "user", "content": "hi"}]}
    statuses = []
    for _ in range(9):
        with mock.patch.object(claude, "client", return_value=fake_client(FakeStream(["ok"]))):
            statuses.append(APIClient().post(URL, body, format="json").status_code)
    assert statuses[:8] == [200] * 8 and statuses[8] == 429
