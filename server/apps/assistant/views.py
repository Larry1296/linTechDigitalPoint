"""Public help chat for the website: anyone can ask, no account needed."""
from django.http import StreamingHttpResponse
from rest_framework import permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .claude import configured, event, stream_answer
from .retrieval import retrieve

MAX_QUESTION = 1000
MAX_ANSWER = 6000
MAX_TURNS = 12  # messages kept from the conversation, oldest dropped first


class AssistantBurstThrottle(AnonRateThrottle):
    scope = "assistant_burst"
    rate = "8/minute"


class AssistantHourlyThrottle(AnonRateThrottle):
    scope = "assistant_hourly"
    rate = "60/hour"


def _conversation(data, max_question=MAX_QUESTION, max_answer=MAX_ANSWER, max_turns=MAX_TURNS):
    """Validated (history, question), or an error message. The browser keeps the conversation."""
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages:
        return None, "Send the conversation as a list of messages."
    clean = []
    for message in messages[-max_turns:]:
        role, content = (message.get("role"), message.get("content")) if isinstance(message, dict) else (None, None)
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            return None, "Each message needs a role (user or assistant) and some text."
        limit = max_question if role == "user" else max_answer
        if len(content) > limit:
            return None, f"Messages can be at most {limit} characters."
        # Turns must alternate, starting with the visitor. Two questions in a row mean the earlier one was never
        # answered (its reply failed): keep only the newer one, so an old question is not answered again with it.
        if clean and clean[-1]["role"] == role == "user":
            clean[-1] = {"role": role, "content": content.strip()}
        elif clean and clean[-1]["role"] == role:
            clean[-1]["content"] += "\n\n" + content.strip()
        else:
            clean.append({"role": role, "content": content.strip()})
    while clean and clean[0]["role"] != "user":
        clean.pop(0)
    if not clean or clean[-1]["role"] != "user":
        return None, "The last message must be the visitor's question."
    return (clean[:-1], clean[-1]["content"]), None


def answer_from_articles(question, passages):
    """The public chat without an AI key: the best-matching help section, as written, if it really matches."""
    from django.conf import settings
    from .retrieval import tokens
    top = passages[0] if passages else None
    asked = set(tokens(question))
    if top and asked and len(asked & set(tokens(f"{top.heading} {top.text}"))) * 2 >= len(asked):
        yield event("text", text=f"**{top.heading}**\n\n{top.text}")
        yield event("sources", items=[top.article])
    else:
        contact = settings.PLATFORM_CONTACT_EMAIL
        yield event("text", text="I couldn't find that in the help articles. Try asking in other words, or "
                    + (f"email the team at {contact}." if contact else "contact the team using the details on this website."))
    yield event("done")


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([AssistantBurstThrottle, AssistantHourlyThrottle])
def chat(request):
    conversation, problem = _conversation(request.data)
    if problem:
        return Response({"detail": problem}, status=400)
    from .models import PublicChatSettings, PublicQuestion
    if not PublicChatSettings.current().enabled:
        return Response({"detail": "The help assistant is switched off right now. Please contact the team instead."}, status=503)
    history, question = conversation
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    passages = retrieve(question, previous)
    # Only the question is kept, with the articles it was answered from, so the owner can see what is missing.
    PublicQuestion.objects.create(question=question, articles=sorted({p.article for p in passages}), answered=bool(passages))
    # No AI key: answer with the help section that matches, as written, rather than nothing.
    stream = stream_answer(history, question, passages) if configured() else answer_from_articles(question, passages)
    response = StreamingHttpResponse(stream, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # let nginx pass each chunk straight through
    return response


DEFAULT_GREETING = ("Hi! I can answer questions about {platform}: how to get started, what it can do for your business, "
                    "pricing and more. What would you like to know?")
DEFAULT_SUGGESTIONS = ["How do I get started?", "How much does it cost?", "Can I import my products from Excel?",
                       "Does it work with M-Pesa?", "Can my staff use it?", "Is my business data safe?"]


@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def public_config(request):
    """What the website's chat shows: whether it is on, its greeting and suggested questions (set by the platform owner)."""
    from django.conf import settings
    from .models import PublicChatSettings
    current = PublicChatSettings.current()
    return Response({"enabled": current.enabled,
                     "greeting": current.greeting or DEFAULT_GREETING.format(platform=settings.PLATFORM_NAME),
                     "suggestions": current.suggestions or DEFAULT_SUGGESTIONS})
