"""Streams the assistant's answer from Claude as server-sent events."""
import json
import logging
import os

import anthropic
from django.conf import settings

from .prompts import question_turn, system_prompt

logger = logging.getLogger(__name__)
_client = None


def configured():
    return bool(settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client():
    global _client
    if _client is None:
        options = {"max_retries": 2, "timeout": anthropic.Timeout(60.0, connect=5.0)}
        if settings.ANTHROPIC_API_KEY:
            options["api_key"] = settings.ANTHROPIC_API_KEY
        _client = anthropic.Anthropic(**options)
    return _client


def event(kind, **data):
    return f"data: {json.dumps({'type': kind, **data})}\n\n"


def stream_answer(history, question, passages):
    """Yields SSE lines: text chunks, then sources and done (or an error)."""
    messages = [*history, {"role": "user", "content": question_turn(question, passages)}]
    try:
        with client().beta.messages.stream(
            model=settings.ASSISTANT_MODEL,
            max_tokens=4096,  # short help answers; a hard ceiling keeps a public endpoint's cost bounded
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            # The instructions are identical on every request, so they are cached.
            system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            # If a safety classifier declines, the API retries on its recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                yield event("text", text=text)
            final = stream.get_final_message()
    except anthropic.RateLimitError:
        logger.warning("Assistant rate limited by the Claude API")
        yield event("error", message="The assistant is busy right now. Please try again in a minute.")
        return
    except anthropic.APIConnectionError:
        logger.warning("Assistant could not reach the Claude API")
        yield event("error", message="The assistant can't connect right now. Please try again shortly.")
        return
    except anthropic.APIStatusError as exc:
        logger.error("Assistant Claude API error %s (request %s): %s", exc.status_code, getattr(exc, "request_id", None), exc.message)
        yield event("error", message="Something went wrong on our side. Please try again shortly.")
        return
    if final.stop_reason == "refusal":
        yield event("refusal", message="Sorry, I can't help with that. Ask me anything about using the platform.")
        return
    if final.stop_reason == "max_tokens":
        yield event("text", text="\n\n_(Answer shortened. Ask me to continue if you need more.)_")
    usage = final.usage
    logger.info("Assistant answer: %s in (%s cached), %s out", usage.input_tokens, usage.cache_read_input_tokens, usage.output_tokens)
    sources = []
    for passage in passages:
        if passage.article not in sources:
            sources.append(passage.article)
    yield event("sources", items=sources[:3])
    yield event("done")
