"""Streams a business assistant answer from Anthropic (Claude) or OpenAI, running the read-only tools in between.

Both providers produce the same server-sent events as the website help chat: ``text`` chunks, ``tool`` (what is
being looked up, for the "Checking sales…" hint), then ``done``, or ``error`` / ``refusal``.
"""
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from apps.tenancy.context import branch_context, organization_context

from . import business_tools
from .business_prompt import business_prompt
from .claude import event

logger = logging.getLogger(__name__)
PROVIDERS = {"anthropic": "Claude (Anthropic)", "openai": "ChatGPT (OpenAI)"}
MAX_ROUNDS = 8  # tool rounds per question; the last round must answer with what it has
MAX_OUTPUT = 16000
LABELS = {"business_overview": "Reading the business profile", "find_products": "Looking up products", "stock_levels": "Checking stock levels",
          "inventory_analysis": "Analysing stock", "sales_summary": "Checking sales", "sales_statistics": "Analysing sales trends",
          "stock_movements": "Checking stock movements", "financial_summary": "Reading the books", "expense_analysis": "Analysing expenses",
          "service_jobs": "Checking service jobs", "mpesa_summary": "Checking M-Pesa", "platform_help": "Searching the help centre",
          "agency_commission": "Checking agency commission", "money_position": "Working out where the money is",
          "money_owed_to_business": "Checking who owes you", "money_business_owes": "Checking what you owe",
          "purchases_and_suppliers": "Checking purchases", "find_sales": "Looking up sales", "top_customers": "Checking customers",
          "investments": "Checking investments", "chamas": "Checking the chamas", "activity_log": "Reading the activity log"}
_clients = {}


def configured(provider):
    if provider == "anthropic":
        return bool(settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if provider == "openai":
        return bool(settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY"))
    return False


def provider_for(organization):
    """The business's chosen provider, else the platform default, else whichever one has a key."""
    chosen = (organization.settings or {}).get("assistant", {}).get("provider")
    for provider in (chosen, settings.BUSINESS_ASSISTANT_PROVIDER, *PROVIDERS):
        if provider in PROVIDERS and configured(provider):
            return provider
    return None


def _anthropic():
    if "anthropic" not in _clients:
        import anthropic
        options = {"max_retries": 2, "timeout": anthropic.Timeout(120.0, connect=5.0)}
        if settings.ANTHROPIC_API_KEY:
            options["api_key"] = settings.ANTHROPIC_API_KEY
        _clients["anthropic"] = anthropic.Anthropic(**options)
    return _clients["anthropic"]


def _openai():
    if "openai" not in _clients:
        import openai
        options = {"max_retries": 2, "timeout": 120.0}
        if settings.OPENAI_API_KEY:
            options["api_key"] = settings.OPENAI_API_KEY
        _clients["openai"] = openai.OpenAI(**options)
    return _clients["openai"]


@contextmanager
def _scope(ctx):
    """The request's business, branch and time zone. A streamed response runs after the tenant middleware has
    returned, so tools re-enter the scope themselves; nothing is held open between chunks."""
    with organization_context(ctx.organization), branch_context(ctx.branch), timezone.override(ZoneInfo(ctx.organization.timezone)):
        yield


def _run_tool(ctx, name, args):
    with _scope(ctx):
        try:
            return business_tools.run(ctx, name, args)
        except Exception:
            logger.exception("Business assistant tool %s failed", name)
            return json.dumps({"error": "This lookup failed on the server. Try a different question or period."}), True


def stream_business_answer(ctx, history, question, provider):
    with _scope(ctx):
        system = business_prompt(ctx)
        tools = business_tools.available(ctx)
    stream = _stream_anthropic if provider == "anthropic" else _stream_openai
    yield from stream(ctx, system, tools, history, question)
    yield event("done")


def _stream_anthropic(ctx, system, tools, history, question):
    import anthropic
    messages = [*history, {"role": "user", "content": question}]
    specs = [{"name": name, "description": description, "input_schema": schema} for name, description, schema in tools]
    usage = [0, 0, 0]
    for round_number in range(MAX_ROUNDS):
        last = round_number == MAX_ROUNDS - 1
        try:
            # Tool inputs here are a few short fields, so the default (validated, buffered) tool input streaming is kept.
            with _anthropic().beta.messages.stream(
                model=settings.BUSINESS_ASSISTANT_ANTHROPIC_MODEL,
                max_tokens=MAX_OUTPUT,
                thinking={"type": "adaptive"},
                output_config={"effort": settings.BUSINESS_ASSISTANT_EFFORT},
                # Stable for this business and role, so the instructions and tool list are cached across questions.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=specs,
                tool_choice={"type": "none"} if last else {"type": "auto"},
                messages=messages,
                # If a safety classifier declines, the API retries on its recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                for text in stream.text_stream:
                    yield event("text", text=text)
                final = stream.get_final_message()
        except anthropic.RateLimitError:
            logger.warning("Business assistant rate limited by the Claude API")
            yield event("error", message="The assistant is busy right now. Please try again in a minute.")
            return
        except anthropic.APIConnectionError:
            logger.warning("Business assistant could not reach the Claude API")
            yield event("error", message="The assistant can't connect right now. Please try again shortly.")
            return
        except anthropic.APIStatusError as exc:
            logger.error("Business assistant Claude API error %s (request %s): %s", exc.status_code, getattr(exc, "request_id", None), exc.message)
            yield event("error", message="Something went wrong on our side. Please try again shortly.")
            return
        usage[0] += final.usage.input_tokens
        usage[1] += final.usage.cache_read_input_tokens or 0
        usage[2] += final.usage.output_tokens
        if final.stop_reason == "refusal":
            yield event("refusal", message="Sorry, I can't help with that. Ask me about your business's stock, sales or accounts.")
            return
        calls = [block for block in final.content if block.type == "tool_use"]
        if final.stop_reason == "max_tokens":
            # A cut-off tool call may carry a partial input: never run it.
            yield event("text", text="\n\n_(Answer shortened. Ask me to continue if you need more.)_")
            break
        if not calls:
            break
        messages.append({"role": "assistant", "content": final.content})
        results = []
        for call in calls:
            yield event("tool", name=call.name, label=LABELS.get(call.name, "Looking this up"))
            text, failed = _run_tool(ctx, call.name, call.input)
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": text, **({"is_error": True} if failed else {})})
        messages.append({"role": "user", "content": results})
        if any(block.type == "text" and block.text.strip() for block in final.content):
            yield event("text", text="\n\n")
    logger.info("Business assistant (anthropic, org %s): %s in (%s cached), %s out", ctx.organization.pk, *usage)


def _stream_openai(ctx, system, tools, history, question):
    import openai
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": question}]
    specs = [{"type": "function", "function": {"name": name, "description": description, "parameters": schema}} for name, description, schema in tools]
    # A stable pseudonymous id per person and business, so OpenAI can tell abusers apart without personal data.
    safety_id = hashlib.sha256(f"{ctx.organization.pk}:{ctx.user.pk}".encode()).hexdigest()[:32]
    usage = [0, 0, 0]
    for round_number in range(MAX_ROUNDS):
        last = round_number == MAX_ROUNDS - 1
        text, calls, finish = "", {}, None
        try:
            stream = _openai().chat.completions.create(
                model=settings.BUSINESS_ASSISTANT_OPENAI_MODEL,
                messages=messages,
                tools=specs,
                tool_choice="none" if last else "auto",
                reasoning_effort=settings.BUSINESS_ASSISTANT_EFFORT,
                max_completion_tokens=MAX_OUTPUT,
                safety_identifier=safety_id,
                prompt_cache_key=f"business-assistant-{ctx.organization.pk}",
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                if chunk.usage:
                    details = chunk.usage.prompt_tokens_details
                    usage[0] += chunk.usage.prompt_tokens
                    usage[1] += (details.cached_tokens or 0) if details else 0
                    usage[2] += chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta.refusal:
                    yield event("refusal", message="Sorry, I can't help with that. Ask me about your business's stock, sales or accounts.")
                    return
                if delta.content:
                    text += delta.content
                    yield event("text", text=delta.content)
                for part in delta.tool_calls or []:
                    slot = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                    slot["id"] = part.id or slot["id"]
                    if part.function:
                        slot["name"] += part.function.name or ""
                        slot["arguments"] += part.function.arguments or ""
                finish = choice.finish_reason or finish
        except openai.RateLimitError:
            logger.warning("Business assistant rate limited by the OpenAI API")
            yield event("error", message="The assistant is busy right now. Please try again in a minute.")
            return
        except openai.APIConnectionError:
            logger.warning("Business assistant could not reach the OpenAI API")
            yield event("error", message="The assistant can't connect right now. Please try again shortly.")
            return
        except openai.APIStatusError as exc:
            logger.error("Business assistant OpenAI API error %s (request %s): %s", exc.status_code, getattr(exc, "request_id", None), exc.message)
            yield event("error", message="Something went wrong on our side. Please try again shortly.")
            return
        if finish == "content_filter":
            yield event("refusal", message="Sorry, I can't help with that. Ask me about your business's stock, sales or accounts.")
            return
        if finish == "length":
            yield event("text", text="\n\n_(Answer shortened. Ask me to continue if you need more.)_")
            break
        if not calls:
            break
        ordered = [calls[i] for i in sorted(calls)]
        messages.append({"role": "assistant", "content": text or None,
                         "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in ordered]})
        for call in ordered:
            yield event("tool", name=call["name"], label=LABELS.get(call["name"], "Looking this up"))
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                result = json.dumps({"error": "The tool input was not valid JSON. Send a JSON object."})
            else:
                result, _ = _run_tool(ctx, call["name"], args)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        if text.strip():
            yield event("text", text="\n\n")
    logger.info("Business assistant (openai, org %s): %s in (%s cached), %s out", ctx.organization.pk, *usage)
