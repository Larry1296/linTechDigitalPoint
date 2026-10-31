"""Each business's own assistant, inside the workspace: it answers from that business's records only.

The tenant middleware has already resolved the signed-in person's business and branch, and refuses
requests without an active membership. Everything the assistant reads goes through the tools in
business_tools, which check the person's permissions again.
"""
from django.http import StreamingHttpResponse
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.core.models import AuditLog
from apps.core.permissions import IsInternalStaff

from .business_chat import PROVIDERS, configured, provider_for, stream_business_answer, stream_offline_answer, unavailable_reason
from .business_tools import Context
from .views import _conversation

MAX_QUESTION = 2000
MAX_ANSWER = 12000
MAX_TURNS = 20


class BusinessAssistantBurstThrottle(UserRateThrottle):
    scope = "business_assistant_burst"
    rate = "10/minute"


class BusinessAssistantDailyThrottle(UserRateThrottle):
    scope = "business_assistant_daily"
    rate = "300/day"


def _manages(request):
    return bool(request.membership and request.membership.role in {"OWNER", "ADMIN"})


@api_view(["POST"])
@permission_classes([IsInternalStaff])
@throttle_classes([BusinessAssistantBurstThrottle, BusinessAssistantDailyThrottle])
def chat(request):
    if request.membership and request.membership.role == "EMPLOYEE":
        # The assistant answers about the business's records and money, which are the owner's.
        return Response({"detail": "The business assistant is for the business owner."}, status=403)
    conversation, problem = _conversation(request.data, MAX_QUESTION, MAX_ANSWER, MAX_TURNS)
    if problem:
        return Response({"detail": problem}, status=400)
    provider = provider_for(request.organization)
    history, question = conversation
    ctx = Context(request.user, request.organization, request.store)
    # Without an AI key the assistant still answers the common questions from the records (offline.py).
    answer = stream_business_answer(ctx, history, question, provider) if provider else stream_offline_answer(ctx, question, unavailable_reason(ctx, None))
    response = StreamingHttpResponse(answer, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, private"
    response["X-Accel-Buffering"] = "no"  # let nginx pass each chunk straight through
    return response


@api_view(["GET", "PUT"])
@permission_classes([IsInternalStaff])
def assistant_settings(request):
    """Which AI provider this business's assistant uses. Owners and admins choose; everyone can see it."""
    organization = request.organization
    if request.method == "PUT":
        if not _manages(request):
            return Response({"detail": "Only the business owner or an admin can change the assistant."}, status=403)
        provider = request.data.get("provider") if isinstance(request.data, dict) else None
        if provider not in PROVIDERS:
            return Response({"provider": f"Choose one of: {', '.join(PROVIDERS)}."}, status=400)
        if not configured(provider):
            return Response({"provider": f"{PROVIDERS[provider]} isn't available on this platform yet."}, status=400)
        before = (organization.settings or {}).get("assistant", {}).get("provider")
        organization.settings = {**(organization.settings or {}), "assistant": {**(organization.settings or {}).get("assistant", {}), "provider": provider}}
        organization.save(update_fields=["settings", "updated_at"])
        AuditLog.objects.create(action="ASSISTANT_PROVIDER_CHANGED", object_type="Organization", object_id=str(organization.pk), user=request.user,
                                before={"provider": before}, after={"provider": provider})
    return Response({
        "provider": provider_for(organization),
        "providers": [{"id": key, "label": label, "available": configured(key)} for key, label in PROVIDERS.items()],
        "can_manage": _manages(request),
    })
