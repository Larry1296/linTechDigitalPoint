from zoneinfo import ZoneInfo
from django.http import JsonResponse
from django.urls import resolve, Resolver404
from django.utils import timezone
from .context import organization_context, branch_context
from .models import Membership, BranchMembership

# Authentication/account recovery and tenant selection do not read business records.
ACCOUNT_PATHS = {"csrf", "login", "logout", "me", "refresh", "session", "unlock", "lock", "activity", "password/change", "password/reset", "password/reset/confirm"}
MODULE_PATHS = {"catalog": "inventory", "inventory": "inventory", "locations": "locations", "commerce": "pos", "cyber": "services", "mpesa": "mpesa", "accounting": "reports", "store": "inventory", "kyama": "kyama"}

def module_for_path(relative):
    if relative in {"inventory/dashboard", "kyama/setup"}:
        return None  # kyama/setup turns kyama management on, within the plan
    if relative.startswith("accounting/expenses") or relative.startswith("accounting/categories"):
        return "expenses"
    if relative == "accounting/administration/users":
        return "staff"
    return MODULE_PATHS.get(relative.split("/")[0])

def resolve_membership(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return None
    memberships = Membership.objects.select_related("organization__subscription__plan").filter(user=request.user, status="ACTIVE", organization__active=True)
    selected = request.session.get("organization_id")
    if selected is not None:
        return memberships.filter(organization_id=selected).first()
    options = list(memberships[:2])
    if len(options) == 1:
        request.session["organization_id"] = options[0].organization_id
        return options[0]
    return None

def effective_modules(organization):
    from .billing import modules_for
    return modules_for(organization)

def resolve_store(request, organization, membership):
    """Resolve the selected branch without trusting a browser supplied ID."""
    if not organization:
        return None
    from .branches import authorized_stores
    with organization_context(organization):
        stores = authorized_stores(request.user, membership)
        selected = request.session.get("branch_id")
        store = stores.filter(pk=selected).first() if selected else None
        if store is None:
            store = stores.first()
        if store:
            request.session["branch_id"] = store.pk
        else:
            request.session.pop("branch_id", None)
        return store

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with organization_context(None), branch_context(None):
            request.user._tenant_permission_cache = {}
            request.membership = resolve_membership(request)
            organization = request.membership.organization if request.membership else None
            request.organization = organization
            request.store = resolve_store(request, organization, request.membership)
            relative = request.path.removeprefix("/api/v1/").strip("/")
            account = relative.startswith("auth/") and relative[5:] in ACCOUNT_PATHS
            # The website's help assistant is public and never reads business records.
            platform = relative.startswith(("tenancy/", "assistant/"))
            business = request.path.startswith("/api/v1/") and not account and not platform
            if business:
                try:
                    resolve(request.path)
                except Resolver404:
                    return self.get_response(request)
                if not request.user.is_authenticated:
                    return JsonResponse({"detail": "Authentication required."}, status=403)
                if not organization:
                    return JsonResponse({"detail": "Select an active business membership.", "code": "organization_required"}, status=403)
                if request.store is None and BranchMembership.objects.filter(
                    user=request.user, store__organization=organization,
                ).exists() and request.membership.role not in {"OWNER", "ADMIN", "MANAGER"}:
                    return JsonResponse({"detail": "No active branch assignment.", "code": "branch_required"}, status=403)
                expected = request.headers.get("X-Organization-ID")
                if expected is not None and expected != str(organization.pk):
                    return JsonResponse({"detail": "The active business changed. Reload the workspace before continuing.", "code": "organization_changed"}, status=409)
                expected_branch = request.headers.get('X-Branch-ID')
                if expected_branch is not None and expected_branch != str(getattr(request.store, 'pk', None)):
                    return JsonResponse({'detail':'The active branch changed. Reload before continuing.', 'code':'branch_changed'}, status=409)
                from .billing import write_allowed
                if request.method not in {"GET", "HEAD", "OPTIONS"} and not write_allowed(organization, relative):
                    return JsonResponse({"detail": "Your subscription has ended, so this is paused. Renew it on the Subscription page to continue.",
                                         "code": "subscription_ended"}, status=403)
                module = module_for_path(relative)
                if module and module not in effective_modules(organization):
                    return JsonResponse({"detail": "This module is not enabled for your business."}, status=403)
            with organization_context(organization), branch_context(request.store if business else None):
                with timezone.override(ZoneInfo(organization.timezone) if organization else None):
                    response = self.get_response(request)
                    if business:
                        response["Cache-Control"] = "private, no-store"
                    return response
