"""Tools only the platform administrator's assistant gets: a summary of every registered business.

General information only: who the business is, its owner's contact, plan, subscription, payments to the platform
and how active it is. Never another business's sales, customers, stock or money: those stay inside each business.
"""
from collections import Counter

from django.db.models import Max
from django.utils import timezone

from apps.tenancy.context import branch_context, organization_context

PLATFORM = "platform.admin"  # pseudo-permission: the signed-in user is the platform administrator


def _when(value):
    return timezone.localtime(value).date().isoformat() if value else None


def _activity(organization):
    """How active the business is, from its activity log and sales count (no amounts)."""
    from apps.commerce.models import Sale
    from apps.core.models import AuditLog
    from apps.core.models import Store
    since = timezone.now() - timezone.timedelta(days=30)
    # The administrator's own branch must not narrow another business's rows: count across all its branches.
    with organization_context(organization), branch_context(None):
        last = AuditLog.objects.aggregate(v=Max("created_at"))["v"]
        return {"last_activity": _when(last), "actions_last_30_days": AuditLog.objects.filter(created_at__gte=since).count(),
                "sales_last_30_days": Sale.objects.filter(status="COMPLETED", created_at__gte=since).count(),
                "branches": Store.objects.count()}


def _row(organization, activity=True):
    from apps.tenancy.billing_api import business_row
    from apps.tenancy.middleware import effective_modules
    row = business_row(organization)
    s = row["subscription"]
    result = {"business": row["name"], "type": row["business_type"] or row["business_model"], "country": row["country"],
              "registered": _when(row["created_at"]), "active": row["active"], "owner": row["owner"],
              "business_phone": row["phone"], "business_email": row["email"], "staff": row["members"],
              "plan": s["plan_name"] or None, "status": s["status"], "ends": _when(s["ends_at"]), "days_left": s["days_left"],
              "complimentary": s["complimentary"], "expiring_soon": s.get("expiring_soon", False),
              "paid_to_platform": row["total_paid"], "last_paid": _when(row["last_paid_at"]),
              "tools_enabled": sorted(effective_modules(organization))}
    if activity:
        result.update(_activity(organization))
    return result


def platform_overview(ctx, args):
    from apps.tenancy.billing_api import _businesses, business_row, platform_summary
    from apps.tenancy.models import SubscriptionPayment
    organizations = list(_businesses())
    summary = platform_summary([business_row(org) for org in organizations])
    signups = Counter(timezone.localtime(org.created_at).strftime("%Y-%m") for org in organizations)
    recent = [{"business": p.organization.name, "plan": p.plan.name, "amount": str(p.amount), "status": p.status, "method": p.method,
               "when": _when(p.paid_at or p.created_at)} for p in SubscriptionPayment.objects.select_related("plan", "organization")[:15]]
    return {"summary": summary, "signups_by_month": dict(sorted(signups.items())), "recent_subscription_payments": recent,
            "note": "Platform-level figures only. Each business's own sales, customers and money are private to it."}


def platform_businesses(ctx, args):
    from apps.tenancy.billing_api import _businesses
    from .business_tools import ToolError, _limit
    status = str(args.get("status", "all")).lower()
    if status not in {"all", "trial", "paying", "ended", "expiring_soon", "complimentary", "inactive"}:
        raise ToolError("status must be one of all, trial, paying, ended, expiring_soon, complimentary, inactive.")
    query = " ".join(str(args.get("query", "")).split()).lower()
    rows = []
    for org in _businesses():
        if query and query not in f"{org.name} {org.business_type} {org.owner.get_full_name() if org.owner else ''} {org.phone} {org.email}".lower():
            continue
        row = _row(org, activity=False)
        keep = {"all": True, "trial": row["status"] == "TRIAL", "ended": row["status"] in {"EXPIRED", "SUSPENDED", "CANCELLED", "UNCONFIGURED"},
                "paying": row["status"] == "ACTIVE" and not row["complimentary"] and row["plan"] is not None,
                "expiring_soon": row["expiring_soon"], "complimentary": row["complimentary"], "inactive": not row["active"]}[status]
        if keep:
            rows.append((org, row))
    limit = _limit(args, 30, 200)
    listed = [{**row, **_activity(org)} for org, row in rows[:limit]]
    return {"filter": status, "query": query or None, "matching": len(rows), "listed": len(listed), "businesses": listed}


def platform_admin_help(ctx, args):
    from .business_tools import ToolError
    from .retrieval import admin_index
    question = " ".join(str(args.get("question", "")).split())
    if not question:
        raise ToolError("Give the question to look up in the administrator's articles.")
    return {"passages": [{"article": p.article, "section": p.heading, "text": p.text} for p in admin_index().search(question, 4)]}
