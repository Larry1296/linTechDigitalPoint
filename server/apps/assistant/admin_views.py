"""The platform owner's controls for the assistants: the public chat's switch and wording, the help articles for the
public chat and for the administrator, and the questions visitors asked. Platform administrator only."""
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.models import AuditLog

from . import business_chat
from .models import HelpArticle, PublicChatSettings, PublicQuestion
from .retrieval import articles, built_in
from .views import DEFAULT_GREETING, DEFAULT_SUGGESTIONS

AUDIENCES = {"public": HelpArticle.PUBLIC, "admin": HelpArticle.ADMIN}
KEEP_QUESTIONS_DAYS = 180


class IsPlatformAdmin(permissions.BasePermission):
    message = "Only the platform administrator can open this."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def _settings_data():
    current = PublicChatSettings.current()
    return {"enabled": current.enabled, "greeting": current.greeting, "suggestions": current.suggestions,
            "default_greeting": DEFAULT_GREETING.format(platform=settings.PLATFORM_NAME), "default_suggestions": DEFAULT_SUGGESTIONS,
            "updated_at": current.updated_at,
            "providers": [{"id": key, "label": label, "available": business_chat.configured(key)} for key, label in business_chat.PROVIDERS.items()],
            "models": {"public": settings.ASSISTANT_MODEL, "business_claude": settings.BUSINESS_ASSISTANT_ANTHROPIC_MODEL,
                       "business_chatgpt": settings.BUSINESS_ASSISTANT_OPENAI_MODEL},
            "default_provider": settings.BUSINESS_ASSISTANT_PROVIDER, "fund_rates": _fund_rates()}


def _fund_rates():
    """The latest looks at money market fund rates, with why any failed: businesses only ever see the rate in use."""
    from apps.accounting import fund_rates
    from apps.market.models import FundRateCheck
    return {"model": settings.FUND_RATE_MODEL, "every_days": fund_rates.REFRESH_DAYS,
            "funds": [{**fund_rates.summary(code), "followed": fund_rates.linked_anywhere(code)} for code in fund_rates.FUNDS],
            "checks": [{"fund": c.fund, "status": c.status, "annual_rate": c.annual_rate, "effective_annual_rate": c.effective_annual_rate,
                        "as_of": c.as_of, "checked_at": c.checked_at, "source_url": c.source_url, "message": c.message}
                       for c in FundRateCheck.objects.order_by("-checked_at", "-pk")[:12]]}


def _record(user, action, after):
    """Platform-level changes are written to the administrator's own business's activity log, when they have one."""
    from apps.tenancy.context import organization_context
    from apps.tenancy.models import Membership
    membership = Membership.objects.filter(user=user, status="ACTIVE").select_related("organization").first()
    if membership:
        with organization_context(membership.organization):
            AuditLog.objects.create(action=action, object_type="Assistant", object_id="platform", user=user, after=after)


class SettingsInput(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    greeting = serializers.CharField(max_length=600, required=False, allow_blank=True)
    suggestions = serializers.ListField(child=serializers.CharField(max_length=120, allow_blank=True, trim_whitespace=True), max_length=8, required=False)


@api_view(["GET", "PUT"])
@permission_classes([IsPlatformAdmin])
def chat_settings(request):
    if request.method == "PUT":
        form = SettingsInput(data=request.data)
        form.is_valid(raise_exception=True)
        current = PublicChatSettings.current()
        for field, value in form.validated_data.items():
            setattr(current, field, [s.strip() for s in value if s.strip()] if field == "suggestions" else value)
        current.updated_by = request.user
        current.save()
        _record(request.user, "PUBLIC_CHAT_SETTINGS_CHANGED", {k: v for k, v in form.validated_data.items()})
    return Response(_settings_data())


def _audience(name):
    if name not in AUDIENCES:
        raise serializers.ValidationError({"audience": "Choose public or admin."})
    return AUDIENCES[name]


@api_view(["GET"])
@permission_classes([IsPlatformAdmin])
def article_list(request, audience):
    return Response({"audience": audience, "articles": articles(_audience(audience))})


class ArticleInput(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    body = serializers.CharField(max_length=40000)
    active = serializers.BooleanField(default=True)

    def validate_body(self, value):
        if not re.search(r"^## \S", value, re.M):
            raise serializers.ValidationError("Write at least one question as a line starting with \"## \", with its answer below it.")
        if re.search(r"^# ", value, re.M):
            raise serializers.ValidationError("Use \"## \" for questions; the article's title goes in the title field.")
        return value.strip()


@api_view(["PUT", "DELETE"])
@permission_classes([IsPlatformAdmin])
def article_detail(request, audience, slug):
    """PUT saves the owner's version (edits a built-in article, or adds one); DELETE goes back to the built-in one, or
    removes an added one."""
    kind = _audience(audience)
    if not re.fullmatch(r"[a-z0-9-]{1,80}", slug):
        return Response({"slug": "Use lowercase letters, numbers and dashes."}, status=400)
    if request.method == "DELETE":
        deleted, _ = HelpArticle.objects.filter(audience=kind, slug=slug).delete()
        if deleted:
            _record(request.user, "HELP_ARTICLE_RESTORED", {"audience": audience, "slug": slug})
        return Response({"audience": audience, "articles": articles(kind)})
    form = ArticleInput(data=request.data)
    form.is_valid(raise_exception=True)
    with transaction.atomic():
        HelpArticle.objects.update_or_create(audience=kind, slug=slug, defaults={**form.validated_data, "updated_by": request.user})
    _record(request.user, "HELP_ARTICLE_SAVED", {"audience": audience, "slug": slug, "title": form.validated_data["title"],
                                                 "active": form.validated_data["active"], "built_in": slug in built_in(kind)})
    return Response({"audience": audience, "articles": articles(kind)})


@api_view(["GET"])
@permission_classes([IsPlatformAdmin])
def questions(request):
    PublicQuestion.objects.filter(created_at__lt=timezone.now() - timedelta(days=KEEP_QUESTIONS_DAYS)).delete()
    rows = PublicQuestion.objects.all()
    if request.query_params.get("unanswered") in {"1", "true"}:
        rows = rows.filter(answered=False)
    since = timezone.now() - timedelta(days=30)
    recent = PublicQuestion.objects.filter(created_at__gte=since)
    return Response({"last_30_days": {"questions": recent.count(), "unanswered": recent.filter(answered=False).count()},
                     "keep_days": KEEP_QUESTIONS_DAYS,
                     "questions": [{"id": q.pk, "question": q.question, "articles": q.articles, "answered": q.answered, "asked_at": q.created_at}
                                   for q in rows[:200]]})
