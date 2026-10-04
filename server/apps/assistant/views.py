"""Public help chat for the website: anyone can ask, no account needed."""
from django.http import StreamingHttpResponse
from rest_framework import permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .claude import configured, stream_answer
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
        # Merge repeated roles so turns alternate, starting with the visitor.
        if clean and clean[-1]["role"] == role:
            clean[-1]["content"] += "\n\n" + content.strip()
        else:
            clean.append({"role": role, "content": content.strip()})
    while clean and clean[0]["role"] != "user":
        clean.pop(0)
    if not clean or clean[-1]["role"] != "user":
        return None, "The last message must be the visitor's question."
    return (clean[:-1], clean[-1]["content"]), None


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([AssistantBurstThrottle, AssistantHourlyThrottle])
def chat(request):
    conversation, problem = _conversation(request.data)
    if problem:
        return Response({"detail": problem}, status=400)
    if not configured():
        return Response({"detail": "The help assistant isn't available right now. Please contact the team instead."}, status=503)
    history, question = conversation
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    passages = retrieve(question, previous)
    response = StreamingHttpResponse(stream_answer(history, question, passages), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # let nginx pass each chunk straight through
    return response
