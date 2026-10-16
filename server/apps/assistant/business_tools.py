"""Read-only tools the business assistant calls to look at one business's records.

Every tool runs inside the request's organization and branch context, so the tenant-scoped
managers only ever return that business's rows (and, for branch staff, that branch's). Each tool
also carries the business permission and module it needs: a person is only offered the tools
their role allows, and buying costs and profit need ``accounting.view_profit`` exactly as on the
Reports page. Tools never write.
"""
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.tenancy.middleware import effective_modules
from apps.tenancy.permissions import has_business_permission, membership_for

from .analytics import abc_classes, daily_series, describe_series, r, safe_div

ZERO = Decimal("0")
MAX_RESULT_CHARS = 24000  # keeps one tool result a reasonable share of the context
MAX_DAYS = 3660  # ten years: enough for "since the business started"


class ToolError(Exception):
    """A problem with the tool's input, reported back to the model so it can correct itself."""


class Context:
    """Who is asking, in which business: decides which tools and fields are available."""

    def __init__(self, user, organization, branch=None):
        self.user, self.organization, self.branch = user, organization, branch
        self.modules = set(effective_modules(organization))
        self.membership = membership_for(user)

    @property
    def platform_admin(self):
        return bool(self.user and self.user.is_active and self.user.is_superuser)

    def can(self, permission):
        from .platform_tools import PLATFORM
        if permission == PLATFORM:
            return self.platform_admin
        return permission is None or has_business_permission(self.user, permission)

    @property
    def sees_profit(self):
        return self.can("accounting.view_profit")


# Input helpers ---------------------------------------------------------------------------------

def _date(value, name):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a date written YYYY-MM-DD, got {value!r}.")


def _beginning():
    """The day the business was created here: the first day it can have records."""
    from apps.tenancy.context import organization_id
    from apps.tenancy.models import Organization
    created = Organization.objects.filter(pk=organization_id()).values_list("created_at", flat=True).first()
    return timezone.localtime(created).date() if created else timezone.localdate()


def _period(args, default_days=30):
    today = timezone.localdate()
    end = _date(args["end_date"], "end_date") if args.get("end_date") else today
    if str(args.get("start_date", "")).lower() == "beginning":
        start = min(_beginning(), end)
    else:
        start = _date(args["start_date"], "start_date") if args.get("start_date") else end - timedelta(days=default_days - 1)
    if start > end:
        raise ToolError("start_date must be on or before end_date.")
    if (end - start).days + 1 > MAX_DAYS:
        raise ToolError(f"Choose a period of at most {MAX_DAYS} days.")
    return start, end


def _limit(args, default=20, most=100):
    try:
        value = int(args.get("limit", default))
    except (TypeError, ValueError):
        raise ToolError("limit must be a whole number.")
    return max(1, min(value, most))


def _money(value):
    return r(value, 2)


def _qty(value):
    return r(value, 3)


# Shared queries --------------------------------------------------------------------------------

def _stock_by_variant():
    """{variant_id: (on_hand, available, value at cost)} from the shelf balances in scope."""
    from apps.inventory.models import StockBalance
    rows = (StockBalance.objects.filter(quantity__gt=0)
            .values("lot__variant_id")
            .annotate(on_hand=Sum("quantity"), reserved=Sum("reserved"), value=Sum(F("quantity") * F("lot__unit_cost"))))
    return {row["lot__variant_id"]: (row["on_hand"] or ZERO, (row["on_hand"] or ZERO) - (row["reserved"] or ZERO), row["value"] or ZERO)
            for row in rows}


def _completed_items(start, end):
    from apps.commerce.models import SaleItem
    return SaleItem.objects.filter(sale__status="COMPLETED", sale__created_at__date__range=(start, end))


def _sold_by_variant(start, end):
    """{variant_id: {units, revenue, cost}} net of returns, revenue excluding tax."""
    result = {}
    for item in _completed_items(start, end).values("variant_id", "quantity", "returned_quantity", "net_amount", "cost"):
        kept = (item["quantity"] - item["returned_quantity"]) / item["quantity"] if item["quantity"] else ZERO
        row = result.setdefault(item["variant_id"], {"units": ZERO, "revenue": ZERO, "cost": ZERO})
        row["units"] += item["quantity"] - item["returned_quantity"]
        row["revenue"] += item["net_amount"] * kept
        row["cost"] += item["cost"] * kept
    return result


def _category_paths():
    """{category_id: [top-level name, ..., own name]}: where each category sits in the category tree."""
    from apps.catalog.models import Category
    parents = {c["pk"]: (c["name"], c["parent_id"]) for c in Category.objects.values("pk", "name", "parent_id")}
    paths = {}
    for pk in parents:
        path, current, seen = [], pk, set()
        while current in parents and current not in seen:
            seen.add(current)
            name, current = parents[current]
            path.insert(0, name)
        paths[pk] = path
    return paths


def _variant_label(variant):
    name = variant.product.name
    return name if variant.name in ("", "Standard") else f"{name} ({variant.name})"


# Tools -----------------------------------------------------------------------------------------

def business_overview(ctx, args):
    from apps.catalog.models import Category, ProductVariant
    from apps.core.models import Store
    from apps.tenancy.models import Membership
    org = ctx.organization
    subscription = getattr(org, "subscription", None)
    data = {
        "business": org.name, "business_type": org.business_type or org.get_business_model_display(), "sector": org.sector,
        "size": org.get_business_size_display(), "country": org.country, "currency": org.currency, "timezone": org.timezone,
        "today": timezone.localdate().isoformat(), "modules_enabled": sorted(ctx.modules),
        "branches": [s.name for s in Store.objects.order_by("name")],
        "current_branch": ctx.branch.name if ctx.branch else "all branches",
        "subscription": {"status": subscription.status, "plan": subscription.plan.name if subscription and subscription.plan_id else None,
                         "ends": subscription.ends_at.date().isoformat() if subscription and subscription.ends_at else None} if subscription else None,
        "your_role": ctx.membership.role.replace("_", " ").title() if ctx.membership else None,
        "staff_members": Membership.objects.filter(organization=org, status="ACTIVE").count(),
        "records_start": _beginning().isoformat(),
    }
    if ctx.can("catalog.view_product"):
        variants = ProductVariant.objects.filter(active=True, product__active=True)
        data["catalog"] = {"active_products": variants.values("product").distinct().count(), "active_variants": variants.count(),
                           "services": variants.filter(product__product_type="SERVICE").count(), "categories": Category.objects.filter(active=True).count()}
    return data


def find_products(ctx, args):
    from apps.catalog.models import ProductVariant
    query = " ".join(str(args.get("query", "")).split())
    if not query:
        raise ToolError("Give a product name, SKU, barcode, brand or category to search for.")
    variants = (ProductVariant.objects.filter(Q(product__name__icontains=query) | Q(name__icontains=query) | Q(sku__iexact=query)
                                              | Q(barcode=query) | Q(product__brand__name__icontains=query) | Q(product__category__name__icontains=query))
                .select_related("product__category", "product__brand").order_by("product__name", "name")[:_limit(args)])
    stock = _stock_by_variant()
    rows = []
    for v in variants:
        on_hand, available, value = stock.get(v.pk, (ZERO, ZERO, ZERO))
        row = {"product": _variant_label(v), "sku": v.sku, "barcode": v.barcode, "category": v.product.category.name,
               "brand": v.product.brand.name if v.product.brand_id else None, "type": v.product.product_type,
               "selling_price": _money(v.selling_price), "lowest_price_allowed": _money(v.minimum_price) if v.minimum_price else None,
               "active": v.active and v.product.active}
        if v.product.product_type == "STOCK_ITEM" and ctx.can("inventory.view_stockbalance"):
            row.update(on_hand=_qty(on_hand), available=_qty(available), minimum_stock=_qty(v.minimum_stock), target_stock=_qty(v.target_stock))
            if ctx.sees_profit and on_hand:
                row.update(stock_value_at_cost=_money(value), average_unit_cost=_money(value / on_hand),
                           margin_pct_at_current_price=r((v.selling_price - value / on_hand) / v.selling_price * 100) if v.selling_price else None)
        rows.append(row)
    return {"query": query, "matches": len(rows), "products": rows}


def stock_levels(ctx, args):
    from apps.catalog.models import ProductVariant
    view = args.get("view", "low")
    if view not in {"low", "out", "all", "overstock"}:
        raise ToolError("view must be one of low, out, all, overstock.")
    category = " ".join(str(args.get("category", "")).split())
    variants = ProductVariant.objects.filter(active=True, product__active=True, product__product_type="STOCK_ITEM").select_related("product__category")
    paths = _category_paths()
    if category:
        # A category at any level: "cables" also finds items in its subcategories.
        wanted = [pk for pk, path in paths.items() if any(category.lower() in name.lower() for name in path)]
        variants = variants.filter(product__category_id__in=wanted)
    stock = _stock_by_variant()
    rows, totals = [], {"items": 0, "units": ZERO, "value": ZERO, "out_of_stock": 0, "low": 0}
    for v in variants:
        on_hand, available, value = stock.get(v.pk, (ZERO, ZERO, ZERO))
        totals["items"] += 1
        totals["units"] += on_hand
        totals["value"] += value
        low = available <= v.minimum_stock and v.minimum_stock > 0
        out = available <= 0
        totals["out_of_stock"] += out
        totals["low"] += low and not out
        over = v.target_stock > 0 and on_hand > v.target_stock * Decimal("1.5")
        if (view == "low" and (low or out)) or (view == "out" and out) or (view == "overstock" and over) or view == "all":
            row = {"product": _variant_label(v), "sku": v.sku, "category": v.product.category.name,
                   "category_path": " › ".join(paths.get(v.product.category_id, [v.product.category.name])), "on_hand": _qty(on_hand),
                   "available": _qty(available), "minimum_stock": _qty(v.minimum_stock), "target_stock": _qty(v.target_stock),
                   "suggested_reorder": _qty(max(v.target_stock - available, ZERO)) if v.target_stock else None}
            if ctx.sees_profit:
                row["value_at_cost"] = _money(value)
            rows.append(row)
    rows.sort(key=lambda row: (row["available"] or 0) - (row["minimum_stock"] or 0))
    limit = _limit(args, 50, 200)
    summary = {"stock_items": totals["items"], "units_on_hand": _qty(totals["units"]), "out_of_stock": totals["out_of_stock"], "low_stock": totals["low"]}
    if ctx.sees_profit:
        summary["stock_value_at_cost"] = _money(totals["value"])
    return {"view": view, "category_filter": category or None, "summary": summary, "listed": min(len(rows), limit), "matching": len(rows), "items": rows[:limit]}


def sales_summary(ctx, args):
    from apps.commerce.models import Payment, Sale
    start, end = _period(args)
    group = args.get("group_by", "day")
    groups = {"day", "week", "month", "product", "category", "channel", "payment_method", "staff", "hour", "weekday"}
    if group not in groups:
        raise ToolError(f"group_by must be one of {', '.join(sorted(groups))}.")
    sales = Sale.objects.filter(status="COMPLETED", created_at__date__range=(start, end))
    agg = sales.aggregate(count=Count("id"), total=Sum("total"), net=Sum("net_total"), discount=Sum("discount"), cogs=Sum("cogs"), profit=Sum("gross_profit"))
    count = agg["count"] or 0
    result = {"period": {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1},
              "totals": {"sales_count": count, "sales_value": _money(agg["total"]), "revenue_excluding_tax": _money(agg["net"]),
                         "discounts_given": _money(agg["discount"]), "average_sale": _money(safe_div(agg["total"], count)),
                         "sales_per_day": r(count / ((end - start).days + 1))},
              "note": "Figures are completed sales at the time of sale; returns made later are reflected in the product and category groupings."}
    if ctx.sees_profit:
        result["totals"].update(cost_of_goods=_money(agg["cogs"]), gross_profit=_money(agg["profit"]),
                                gross_margin_pct=r(safe_div(agg["profit"], agg["net"]) * 100) if agg["net"] else None)
    rows = defaultdict(lambda: {"sales": 0, "value": ZERO, "profit": ZERO})
    if group in {"day", "week", "month", "channel", "staff", "hour", "weekday"}:
        for sale in sales.values("created_at", "channel", "total", "gross_profit", "created_by__first_name", "created_by__username"):
            local = timezone.localtime(sale["created_at"])
            key = {"day": local.date().isoformat(), "week": f"{local.isocalendar().year}-W{local.isocalendar().week:02d}",
                   "month": local.strftime("%Y-%m"), "channel": sale["channel"], "hour": f"{local.hour:02d}:00",
                   "weekday": local.strftime("%A"),
                   "staff": sale["created_by__first_name"] or sale["created_by__username"] or "Unknown"}[group]
            rows[key]["sales"] += 1
            rows[key]["value"] += sale["total"]
            rows[key]["profit"] += sale["gross_profit"]
    elif group == "payment_method":
        for p in Payment.objects.filter(sale__in=sales, status="COMPLETED").values("method").annotate(n=Count("sale", distinct=True), v=Sum("amount")):
            rows[p["method"]] = {"sales": p["n"], "value": p["v"], "profit": None}
    else:
        from apps.catalog.models import ProductVariant
        sold = _sold_by_variant(start, end)
        variants = {v.pk: v for v in ProductVariant.objects.filter(pk__in=sold).select_related("product__category")}
        for variant_id, row in sold.items():
            v = variants[variant_id]
            key = _variant_label(v) if group == "product" else v.product.category.name
            rows[key]["sales"] += row["units"]
            rows[key]["value"] += row["revenue"]
            rows[key]["profit"] += row["revenue"] - row["cost"]
    listed = []
    for key, row in rows.items():
        entry = {group: key, "value": _money(row["value"])}
        if group in {"product", "category"}:
            entry["units_sold"] = _qty(row["sales"])
        else:
            entry["sales"] = row["sales"]
        if ctx.sees_profit and row["profit"] is not None:
            entry["gross_profit"] = _money(row["profit"])
        listed.append(entry)
    if group in {"day", "week", "month", "hour"}:
        listed.sort(key=lambda row: row[group])
    else:
        listed.sort(key=lambda row: row["value"] or 0, reverse=True)
    limit = _limit(args, 60, 400)
    result.update(group_by=group, groups=len(listed), rows=listed[:limit])
    return result


def sales_statistics(ctx, args):
    from apps.commerce.models import Sale
    start, end = _period(args, default_days=90)
    # Days before the business existed are not "no sales": they would drag the averages and trend down.
    beginning = _beginning()
    clamped = start < beginning <= end
    start = max(start, beginning) if beginning <= end else start
    metric = args.get("metric", "revenue")
    if metric not in {"revenue", "sales_count", "gross_profit"}:
        raise ToolError("metric must be revenue, sales_count or gross_profit.")
    if metric == "gross_profit" and not ctx.sees_profit:
        raise ToolError("This person's role cannot see profit. Use revenue or sales_count.")
    per_day = defaultdict(lambda: ZERO)
    for sale in Sale.objects.filter(status="COMPLETED", created_at__date__range=(start, end)).values("created_at", "total", "gross_profit"):
        day = timezone.localtime(sale["created_at"]).date()
        per_day[day] += {"revenue": sale["total"], "sales_count": 1, "gross_profit": sale["gross_profit"]}[metric]
    series = daily_series(per_day, start, end)
    stats = describe_series(series, forecast_days=_limit({"limit": args.get("forecast_days", 7)}, 7, 30))
    # The same-length period just before, for a like-for-like comparison.
    length = (end - start).days + 1
    before = Sale.objects.filter(status="COMPLETED", created_at__date__range=(start - timedelta(days=length), start - timedelta(days=1)))
    previous = (before.count() if metric == "sales_count" else before.aggregate(v=Sum("total" if metric == "revenue" else "gross_profit"))["v"] or ZERO)
    current = sum(v for _, v in series)
    return {"metric": metric, "period": {"start": start.isoformat(), "end": end.isoformat()}, "statistics": stats,
            **({"records_start": beginning.isoformat()} if clamped else {}),
            "previous_period_total": r(previous), "change_vs_previous_period_pct": r((current - float(previous)) / float(previous) * 100) if previous else None,
            "method": "Least-squares trend over daily totals (days without sales count as 0); unusual days have |z| ≥ 2; "
                      "forecast = trend continued × weekday pattern (with 14+ days of history), range ≈ 95%."}


def inventory_analysis(ctx, args):
    from apps.catalog.models import ProductVariant
    days = _limit({"limit": args.get("days", 90)}, 90, MAX_DAYS)
    end = timezone.localdate()
    start = end - timedelta(days=days - 1)
    # Averages per day count only the days the business has existed.
    beginning = _beginning()
    clamped = start < beginning
    if clamped:
        start = min(beginning, end)
        days = (end - start).days + 1
    sold = _sold_by_variant(start, end)
    stock = _stock_by_variant()
    variants = ProductVariant.objects.filter(active=True, product__active=True, product__product_type="STOCK_ITEM").select_related("product__category")
    rows = []
    for v in variants:
        on_hand, available, value = stock.get(v.pk, (ZERO, ZERO, ZERO))
        s = sold.get(v.pk, {"units": ZERO, "revenue": ZERO, "cost": ZERO})
        daily = s["units"] / days
        row = {"product": _variant_label(v), "sku": v.sku, "category": v.product.category.name, "units_sold": _qty(s["units"]),
               "revenue": _money(s["revenue"]), "on_hand": _qty(on_hand), "avg_units_per_day": r(daily, 3),
               "days_of_cover": r(available / daily, 1) if daily else None,
               "sell_through_pct": r(s["units"] / (s["units"] + on_hand) * 100) if s["units"] + on_hand else None}
        if ctx.sees_profit:
            row.update(stock_value_at_cost=_money(value), gross_profit=_money(s["revenue"] - s["cost"]),
                       # Annualised turnover: cost of goods sold over the stock currently held at cost.
                       annual_turnover=r(float(s["cost"]) / float(value) * 365 / days, 2) if value else None,
                       gmroi=r(safe_div(s["revenue"] - s["cost"], value), 2) if value else None)
        rows.append(row)
    ranked = abc_classes(rows, "revenue")
    dead = [row for row in ranked if not row["units_sold"] and row["on_hand"]]
    at_risk = sorted((row for row in ranked if row["days_of_cover"] is not None and row["days_of_cover"] < 14), key=lambda row: row["days_of_cover"])
    classes = {c: {"items": sum(1 for row in ranked if row["abc_class"] == c),
                   "revenue_share_pct": r(sum(row["share_pct"] for row in ranked if row["abc_class"] == c))} for c in "ABC"}
    limit = _limit(args, 25, 100)
    result = {"period_days": days, **({"records_start": beginning.isoformat()} if clamped else {}), "stock_items": len(ranked), "abc_summary": classes,
              "top_sellers": ranked[:limit], "running_out_within_14_days": at_risk[:limit],
              "dead_stock_no_sales_in_period": dead[:limit], "dead_stock_count": len(dead),
              "method": "ABC (Pareto) by revenue: A = first 80%, B = next 15%, C = last 5%. Days of cover = available ÷ average daily units sold. "
                        "Sell-through = sold ÷ (sold + on hand)."}
    if ctx.sees_profit:
        result["dead_stock_value_at_cost"] = _money(sum(Decimal(str(row["stock_value_at_cost"] or 0)) for row in dead))
    return result


def stock_movements(ctx, args):
    from apps.inventory.models import Movement, StockAdjustment
    start, end = _period(args)
    moves = Movement.objects.filter(created_at__date__range=(start, end))
    sku = str(args.get("sku", "")).strip()
    if sku:
        moves = moves.filter(variant__sku__iexact=sku)
    by_type = [{"type": row["movement_type"], "movements": row["n"], "units": _qty(row["q"])}
               for row in moves.values("movement_type").annotate(n=Count("id"), q=Sum("quantity")).order_by("-n")]
    adjustments = StockAdjustment.objects.filter(created_at__date__range=(start, end))
    if sku:
        adjustments = adjustments.filter(variant__sku__iexact=sku)
    reasons = [{"reason": row["reason"], "count": row["n"], "units": _qty(row["q"])}
               for row in adjustments.values("reason").annotate(n=Count("id"), q=Sum("amount")).order_by("-n")]
    sold_units = sum((row["units"] for row in _sold_by_variant(start, end).values()), ZERO)
    lost = -(adjustments.filter(amount__lt=0).aggregate(v=Sum("amount"))["v"] or ZERO)
    recent = [{"when": timezone.localtime(a.created_at).strftime("%Y-%m-%d %H:%M"), "product": _variant_label(a.variant), "change": _qty(a.amount),
               "reason": a.reason, "by": a.performed_by.get_username()}
              for a in adjustments.select_related("variant__product", "performed_by").order_by("-created_at")[:_limit(args, 15, 50)]]
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "sku": sku or None, "movements_by_type": by_type,
            "adjustments_by_reason": reasons, "units_removed_by_adjustments": _qty(lost), "units_sold": _qty(sold_units),
            "shrinkage_rate_pct": r(lost / (lost + sold_units) * 100) if lost + sold_units else None, "recent_adjustments": recent}


def financial_summary(ctx, args):
    from apps.accounting.reports import summary
    start, end = _period(args)
    data = summary(ctx.user, {"start": start.isoformat(), "end": end.isoformat()})
    data.pop("filters", None)
    data["period"] = {"start": start.isoformat(), "end": end.isoformat()}
    data["basis_explained"] = ("Accrual basis from the posted books: revenue when earned, costs when incurred. money_received is cash "
                               "actually collected, which is not the same as revenue.")
    daily = data.pop("daily_sales", {})
    if daily:
        series = daily_series({date.fromisoformat(k): v for k, v in daily.items()}, start, end)
        data["revenue_statistics"] = {k: v for k, v in describe_series(series, forecast_days=0).items() if k != "forecast_next_days"}
    return data


def expense_analysis(ctx, args):
    from apps.inventory.dashboard import pnl_rows
    start, end = _period(args)
    by_account, by_unit, by_month = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    revenue = ZERO
    for row in pnl_rows(start, end):
        if row["field"] == "revenue":
            revenue += row["amount"]
        elif row["field"] in {"expenses", "stock_corrections"}:
            by_account[row["account"]] += row["amount"]
            by_unit[row["unit"]] += row["amount"]
            by_month[row["date"].strftime("%Y-%m")] += row["amount"]
    total = sum(by_account.values(), ZERO)
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "total_expenses": _money(total),
            "expenses_as_pct_of_revenue": r(total / revenue * 100) if revenue else None,
            "by_category": sorted(({"category": k, "amount": _money(v), "share_pct": r(v / total * 100) if total else None} for k, v in by_account.items()),
                                  key=lambda row: row["amount"] or 0, reverse=True),
            "by_business_unit": {k: _money(v) for k, v in by_unit.items()}, "by_month": {k: _money(v) for k, v in sorted(by_month.items())}}


def _minutes(start, finish):
    return round((finish - start).total_seconds() / 60) if start and finish else None


def service_jobs(ctx, args):
    from apps.cyber.models import CyberJob, CyberJobLine
    start, end = _period(args)
    jobs = CyberJob.objects.filter(created_at__date__range=(start, end)).exclude(sale__status="CANCELLED")
    by_status = {row["status"]: row["n"] for row in jobs.values("status").annotate(n=Count("id"))}
    # A job completed at the counter is never "started": its time runs from when it was opened.
    done = jobs.filter(status="COMPLETED", completed_at__isnull=False).only("created_at", "started_at", "completed_at")
    minutes = [_minutes(j.started_at or j.created_at, j.completed_at) for j in done]
    top = [{"service": row["service_name"], "jobs": row["n"], "quantity": _qty(row["q"]), "value": _money(row["v"])}
           for row in CyberJobLine.objects.filter(job__in=jobs.filter(status="COMPLETED")).values("service_name")
           .annotate(n=Count("job", distinct=True), q=Sum("quantity"), v=Sum("line_total")).order_by("-v")[:_limit(args)]]
    overdue = CyberJob.objects.exclude(status__in=["COMPLETED", "CANCELLED"]).filter(due_at__lt=timezone.now()).count()
    listed = []
    for job in jobs.select_related("customer", "operator", "sale").prefetch_related("lines", "sale__payments").order_by("-created_at")[:_limit(args, 20, 100)]:
        listed.append({
            "number": job.number, "status": job.status, "opened": timezone.localtime(job.created_at).strftime("%Y-%m-%d %H:%M"),
            "completed": timezone.localtime(job.completed_at).strftime("%Y-%m-%d %H:%M") if job.completed_at else None,
            "minutes_to_complete": _minutes(job.started_at or job.created_at, job.completed_at),
            "due": timezone.localtime(job.due_at).strftime("%Y-%m-%d %H:%M") if job.due_at else None,
            "customer": _customer_name(job.customer) if job.customer_id else (job.walk_in_customer_name or "Walk-in"), "phone": job.phone,
            "served_by": _customer_name(job.operator) if job.operator_id else None,
            "services": [{"service": line.service_name, "quantity": _qty(line.quantity), "unit_price": _money(line.unit_price),
                          "total": _money(line.line_total)} for line in job.lines.all()],
            "discount": _money(job.discount), "total": _money(job.total),
            "paid_by": [{"method": p.method, "amount": _money(p.amount)} for p in job.sale.payments.all()] if job.sale_id else [],
            "notes": job.notes})
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "jobs_by_status": by_status,
            "completed_value": _money(jobs.filter(status="COMPLETED").aggregate(v=Sum("total"))["v"]),
            "average_minutes_to_complete": round(sum(minutes) / len(minutes)) if minutes else None, "open_jobs_overdue_now": overdue,
            "top_services": top, "jobs": listed}


def _mpesa_row(t):
    return {"when": timezone.localtime(t.occurred_at).strftime("%Y-%m-%d %H:%M"), "type": t.transaction_type, "amount": _money(t.amount),
            "customer": t.customer_name, "phone": t.customer_phone, "mpesa_code": t.provider_reference or "",
            "reference": t.internal_reference, "paid_by": t.paid_by, "cash_change": _money(t.cash_delta), "float_change": _money(t.float_delta),
            "by": _customer_name(t.performed_by), "reversed": hasattr(t, "reversal"),
            "reverses": t.reversal_of.internal_reference if t.reversal_of_id else None, "notes": t.notes}


def _shift(session, limit):
    from apps.mpesa.services import session_balances
    tx = session.transactions.filter(status="POSTED")
    cash, electronic_float = session_balances(session)
    shift = {"outlet": session.outlet.display_name, "operator": _customer_name(session.operator), "status": session.status,
             "opened": timezone.localtime(session.opened_at).strftime("%Y-%m-%d %H:%M"),
             "closed": timezone.localtime(session.closed_at).strftime("%Y-%m-%d %H:%M") if session.closed_at else None,
             "opening_cash": _money(session.opening_cash), "opening_float": _money(session.opening_float),
             "cash_now" if session.status == "OPEN" else "expected_cash_at_close": _money(cash),
             "float_now" if session.status == "OPEN" else "expected_float_at_close": _money(electronic_float),
             "transactions_by_type": [{"type": row["transaction_type"], "count": row["n"], "amount": _money(row["v"])}
                                      for row in tx.values("transaction_type").annotate(n=Count("id"), v=Sum("amount")).order_by("-v")],
             "transactions": [_mpesa_row(t) for t in tx.select_related("performed_by", "reversal_of", "reversal").order_by("-occurred_at", "-id")[:limit]]}
    if session.status != "OPEN":
        shift.update(counted_cash=_money(session.closing_cash_actual), counted_float=_money(session.closing_float_actual))
    return shift


def mpesa_summary(ctx, args):
    from apps.mpesa.models import MpesaCommissionEntry, MpesaReconciliation, MpesaSession, MpesaTransaction
    start, end = _period(args)
    limit = _limit(args, 30, 200)
    tx = MpesaTransaction.objects.filter(occurred_at__date__range=(start, end), status="POSTED")
    by_type = [{"type": row["transaction_type"], "count": row["n"], "amount": _money(row["v"])}
               for row in tx.values("transaction_type").annotate(n=Count("id"), v=Sum("amount")).order_by("-v")]
    recs = MpesaReconciliation.objects.filter(created_at__date__range=(start, end))
    sessions = MpesaSession.objects.select_related("outlet", "operator")
    shifts = [_shift(s, limit) for s in sessions.filter(status="OPEN").order_by("-opened_at")]
    shifts += [_shift(s, limit) for s in sessions.filter(status="CLOSED", opened_at__date__range=(start, end)).order_by("-opened_at")[:5]]
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "transactions_by_type": by_type,
            "transactions": tx.count(),
            "commission_earned_in_period": _money(MpesaCommissionEntry.objects.filter(period__range=(start.replace(day=1), end), reversed_at__isnull=True)
                                                  .aggregate(v=Sum("amount"))["v"]),
            "reconciliations": recs.count(), "cash_variance_total": _money(recs.aggregate(v=Sum("cash_variance"))["v"]),
            "float_variance_total": _money(recs.aggregate(v=Sum("float_variance"))["v"]),
            "sessions_open_now": len([s for s in shifts if s["status"] == "OPEN"]), "shifts": shifts,
            "latest_transactions": [_mpesa_row(t) for t in tx.select_related("performed_by", "reversal_of", "reversal").order_by("-occurred_at", "-id")[:limit]]}


def agency_commission(ctx, args):
    from apps.mpesa.api import money_in_operation
    from apps.mpesa.commission import due_month, monthly_profit
    from apps.mpesa.models import MpesaCommissionEntry, MpesaOutlet
    months = _limit({"limit": args.get("months", 12)}, 12, 60)
    rows = monthly_profit(months)
    entries = [{"month": e.period.strftime("%B %Y"), "amount": _money(e.amount), "paid_on": timezone.localtime(e.recognized_at).date().isoformat(),
                "went_to": e.settlement_method, "undone": bool(e.reversed_at), "undo_reason": e.reverse_reason or None, "notes": e.notes or None}
               for e in MpesaCommissionEntry.objects.order_by("-period", "-recognized_at")[:_limit(args, 24, 60)]]
    due = due_month()
    return {"months": [{"month": row["month"].strftime("%B %Y"), "commission_earned": _money(row["commission"]),
                        "agency_running_costs": _money(row["expenses"]), "profit": _money(row["profit"])} for row in rows],
            "commission_not_yet_recorded_for": due.strftime("%B %Y") if due else None,
            "money_in_operation": [{"outlet": o.display_name, **{k: (_money(v) if isinstance(v, Decimal) else v) for k, v in money_in_operation(o).items()}}
                                   for o in MpesaOutlet.objects.all()],
            "entries": entries,
            "explained": "Commission counts in the month it was earned. Undone entries do not count. Deposits, withdrawals and airtime "
                         "principal are never income."}


def money_position(ctx, args):
    """Where the money is and what the business is worth now: owns, owes, net worth, and how it changed."""
    from apps.accounting.net_worth import snapshot
    from apps.accounting.statements import payables, receivables
    stock = sum((value for _, _, value in _stock_by_variant().values()), ZERO) if ctx.can("inventory.view_stockbalance") else None
    owed_to_us = sum((max(row["owed"], ZERO) for row in receivables()), ZERO)
    owing = payables()
    we_owe = sum((row["owed"] for row in owing["suppliers"]), ZERO)
    data = snapshot(stock=stock, receivables=owed_to_us, payables=we_owe, save=False)

    def clean(value):
        if isinstance(value, Decimal):
            return _money(value)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in {"key"}}
        return value
    history = data.pop("history", None) or []
    data = clean(data)
    data["net_worth_history"] = clean(history[-30:]) if isinstance(history, list) else None
    data["explained"] = ("Shop money is what the cash book says should be in each place (the last count is shown beside it). The agency is "
                         "the money in operation now. Stock is at cost. Owes = suppliers for stock received and running costs not yet paid.")
    return data


def _ageing(days):
    return "0-30 days" if days <= 30 else "31-60 days" if days <= 60 else "61-90 days" if days <= 90 else "over 90 days"


def money_owed_to_business(ctx, args):
    from apps.accounting.loans import outstanding, status
    from apps.accounting.models import Loan
    from apps.accounting.statements import receivables
    today = timezone.localdate()
    by_customer, ages = defaultdict(lambda: {"owed": ZERO, "sales": 0, "oldest": None, "overdue": ZERO}), defaultdict(lambda: ZERO)
    refunds_due = ZERO
    for row in receivables():
        if row["owed"] < 0:
            refunds_due += -row["owed"]
            continue
        sold_on = timezone.localtime(row["date"]).date()
        entry = by_customer[row["customer"]]
        entry["owed"] += row["owed"]
        entry["sales"] += 1
        entry["oldest"] = min(entry["oldest"] or sold_on, sold_on)
        if row["due_date"] and row["due_date"] < today:
            entry["overdue"] += row["owed"]
        ages[_ageing((today - sold_on).days)] += row["owed"]
    customers = sorted(({"customer": name, "owed": _money(v["owed"]), "unpaid_sales": v["sales"], "oldest_unpaid_sale": v["oldest"].isoformat(),
                         "overdue": _money(v["overdue"])} for name, v in by_customer.items()), key=lambda row: row["owed"] or 0, reverse=True)
    result = {"customers_owe_total": _money(sum((v["owed"] for v in by_customer.values()), ZERO)), "customers_owing": len(customers),
              "by_age": {k: _money(ages[k]) for k in ["0-30 days", "31-60 days", "61-90 days", "over 90 days"] if ages[k]},
              "customers": customers[:_limit(args, 30, 200)], "refunds_the_business_owes_customers": _money(refunds_due)}
    if ctx.can("accounting.view_loan"):
        loans = []
        for loan in Loan.objects.filter(cancelled_at__isnull=True).prefetch_related("repayments"):
            left = outstanding(loan)
            if left > 0:
                loans.append({"borrower": loan.borrower_name, "lent": _money(loan.amount), "lent_on": loan.lent_on.isoformat(), "due": loan.due_date.isoformat(),
                              "still_owed": _money(left), "status": status(loan, today)})
        result["money_lent_out"] = {"total_still_owed": _money(sum((Decimal(str(l["still_owed"])) for l in loans), ZERO)), "loans": loans}
    return result


def money_business_owes(ctx, args):
    from apps.accounting.statements import payables
    owing = payables()
    today = timezone.localdate()
    suppliers = defaultdict(lambda: {"owed": ZERO, "purchases": 0, "oldest": None})
    for row in owing["suppliers"]:
        received = timezone.localtime(row["date"]).date() if hasattr(row["date"], "tzinfo") and row["date"].tzinfo else row["date"]
        entry = suppliers[row["name"]]
        entry["owed"] += row["owed"]
        entry["purchases"] += 1
        entry["oldest"] = min(entry["oldest"] or received, received)
    bills = [{"bill": row["name"], "description": row["reference"], "date": str(row["date"]), "due": str(row["due_date"]) if row["due_date"] else None,
              "owed": _money(row["owed"]), "overdue": bool(row["due_date"] and row["due_date"] < today)} for row in owing["bills"]]
    listed = sorted(({"supplier": name, "owed": _money(v["owed"]), "unpaid_purchases": v["purchases"], "oldest": str(v["oldest"])}
                     for name, v in suppliers.items()), key=lambda row: row["owed"] or 0, reverse=True)
    return {"suppliers_total": _money(sum((v["owed"] for v in suppliers.values()), ZERO)), "suppliers": listed[:_limit(args, 30, 200)],
            "unpaid_bills_total": _money(sum((Decimal(str(b["owed"])) for b in bills), ZERO)), "unpaid_bills": bills[:_limit(args, 30, 200)]}


def purchases_and_suppliers(ctx, args):
    from apps.accounting.models import SupplierPurchase
    from apps.accounting.services import purchase_outstanding
    start, end = _period(args)
    from apps.accounting.supplier_settlement import real_purchases
    rows = real_purchases(SupplierPurchase.objects.filter(receipt__received_at__date__range=(start, end))).select_related("supplier", "receipt")
    by_supplier = defaultdict(lambda: {"bought": ZERO, "unpaid": ZERO, "purchases": 0})
    recent = []
    for p in rows.order_by("-receipt__received_at"):
        name = p.supplier.name if p.supplier_id else "Supplier not named"
        left = purchase_outstanding(p)
        by_supplier[name]["bought"] += p.amount
        by_supplier[name]["unpaid"] += left
        by_supplier[name]["purchases"] += 1
        if len(recent) < _limit(args, 15, 60):
            recent.append({"date": timezone.localtime(p.receipt.received_at).date().isoformat(), "supplier": name, "receipt": p.receipt.receipt_number,
                           "amount": _money(p.amount), "still_owed": _money(left)})
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "total_bought": _money(sum((v["bought"] for v in by_supplier.values()), ZERO)),
            "by_supplier": sorted(({"supplier": k, "bought": _money(v["bought"]), "still_owed": _money(v["unpaid"]), "purchases": v["purchases"]}
                                   for k, v in by_supplier.items()), key=lambda row: row["bought"] or 0, reverse=True),
            "recent_purchases": recent}


def _customer_name(user):
    return (user.get_full_name() or user.username) if user else "Walk-in"


def find_sales(ctx, args):
    """One sale by its number, or a customer's sales and what they owe."""
    from apps.accounts.models import CustomerProfile
    from apps.commerce.models import Sale
    from apps.commerce.returns import sale_balance
    number = str(args.get("sale_number", "")).strip()
    customer = " ".join(str(args.get("customer", "")).split())
    if not number and not customer:
        raise ToolError("Give a sale_number, or a customer name or phone.")
    sales = Sale.objects.select_related("customer", "created_by").prefetch_related("items__variant__product", "payments")
    if number:
        sales = sales.filter(number__iexact=number)
    else:
        users = CustomerProfile.objects.filter(Q(phone__icontains=customer) | Q(user__first_name__icontains=customer)
                                               | Q(user__last_name__icontains=customer) | Q(user__username__icontains=customer)).values("user")
        sales = sales.filter(customer__in=users)
    rows = []
    for sale in sales.order_by("-created_at")[:_limit(args, 10, 50)]:
        row = {"number": sale.number, "when": timezone.localtime(sale.created_at).strftime("%Y-%m-%d %H:%M"), "status": sale.status,
               "channel": sale.channel, "customer": _customer_name(sale.customer), "sold_by": _customer_name(sale.created_by),
               "total": _money(sale.total), "discount": _money(sale.discount), "still_owed": _money(sale_balance(sale)),
               "due_date": sale.due_date.isoformat() if sale.due_date else None,
               "items": [{"product": _variant_label(i.variant), "quantity": _qty(i.quantity), "returned": _qty(i.returned_quantity),
                          "unit_price": _money(i.unit_price), "discount": _money(i.discount)} for i in sale.items.all()],
               "payments": [{"method": p.method, "amount": _money(p.amount), "status": p.status} for p in sale.payments.all()]}
        if ctx.sees_profit:
            row["gross_profit"] = _money(sale.gross_profit)
        rows.append(row)
    result = {"matches": len(rows), "sales": rows}
    if customer and rows:
        everything = Sale.objects.filter(customer__in=CustomerProfile.objects.filter(Q(phone__icontains=customer) | Q(user__first_name__icontains=customer)
                                         | Q(user__last_name__icontains=customer) | Q(user__username__icontains=customer)).values("user"), status="COMPLETED")
        agg = everything.aggregate(n=Count("id"), v=Sum("total"))
        first = everything.order_by("created_at").values_list("created_at", flat=True).first()
        result["customer_history"] = {"completed_sales": agg["n"], "total_spent": _money(agg["v"]),
                                      "first_purchase": timezone.localtime(first).date().isoformat() if first else None}
    return result


def top_customers(ctx, args):
    from apps.commerce.models import Sale
    start, end = _period(args, default_days=90)
    sales = Sale.objects.filter(status="COMPLETED", created_at__date__range=(start, end))
    named = sales.filter(customer__isnull=False)
    earlier = set(Sale.objects.filter(status="COMPLETED", created_at__date__lt=start, customer__isnull=False).values_list("customer", flat=True))
    rows = []
    for row in named.values("customer", "customer__first_name", "customer__last_name", "customer__username").annotate(n=Count("id"), v=Sum("total")).order_by("-v"):
        rows.append({"customer": f"{row['customer__first_name']} {row['customer__last_name']}".strip() or row["customer__username"],
                     "sales": row["n"], "spent": _money(row["v"]), "new_in_period": row["customer"] not in earlier})
    walk_in = sales.filter(customer__isnull=True).aggregate(n=Count("id"), v=Sum("total"))
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "named_customers": len(rows),
            "new_customers": sum(1 for row in rows if row["new_in_period"]), "returning_customers": sum(1 for row in rows if not row["new_in_period"]),
            "walk_in_sales": walk_in["n"], "walk_in_value": _money(walk_in["v"]), "customers": rows[:_limit(args, 20, 100)]}


def investments(ctx, args):
    from apps.accounting import fund_rates
    from apps.accounting.investment_interest import earnings, estimate, rate_now
    from apps.accounting.investments import totals, value
    from apps.accounting.models import Investment
    rows = []
    for inv in Investment.objects.all():
        t = totals(inv)
        guess, rate = estimate(inv), rate_now(inv)
        fund = fund_rates.summary(inv.fund)
        row = {"investment": inv.name, "value_now": _money(value(inv)),
               **{k: (_money(v) if isinstance(v, Decimal) else v) for k, v in (t or {}).items()}}
        if rate is not None:
            balance = guess["value"] if guess else value(inv)
            pace = earnings(balance, rate, inv.tax_rate)
            row["yearly_rate_now"] = f"{rate}%"
            row["rate_source"] = (f"{fund['name']}'s published rate as of {fund['as_of']}, kept up to date automatically"
                                  if fund and fund["annual_rate"] is not None else "the rate recorded by the business")
            row["earns_after_tax"] = {period: _money(pace[period]["net"]) for period in ("day", "month", "year")}
            row["withholding_tax"] = f"{inv.tax_rate}%"
        if guess:
            row["estimated_interest_since_last_statement"] = _money(guess["net"])
            row["estimated_value_today"] = _money(guess["value"])
        rows.append(row)
    return {"investments": rows, "total_value": _money(sum((Decimal(str(row["value_now"] or 0)) for row in rows), ZERO)),
            "explained": "Value is from recorded deposits, withdrawals, interest and fees; interest not yet on a statement is not counted. "
                         "earns_after_tax is what the money earns now at the current yearly rate after withholding tax: a day, an "
                         "average month, and a year with each month's interest earning interest after it is added."}


def chamas(ctx, args):
    from apps.chama.api import chama_summary
    from apps.chama.models import Chama
    today = timezone.localdate()

    def clean(value):
        if isinstance(value, Decimal):
            return _money(value)
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k != "id"}
        return value
    return {"chamas": [clean(chama_summary(chama, today)) for chama in Chama.objects.prefetch_related("members")],
            "note": "Members' ID numbers and phone numbers are never shown here."}


def chama_members(ctx, args):
    """One chama's members: role, when they joined, what they paid, owe, are late with, fines, and their next turn."""
    from apps.chama.api import chama_detail
    from apps.chama.models import Chama
    name = " ".join(str(args.get("chama", "")).split())
    chamas = Chama.objects.all()
    chosen = chamas.filter(name__icontains=name).first() if name else (chamas.first() if chamas.count() == 1 else None)
    if not chosen:
        names = list(chamas.values_list("name", flat=True))
        if not names:
            return {"chama": None, "members": [], "note": "No chama is registered in this business."}
        raise ToolError(f"No chama called {name!r}. Chamas here: {', '.join(names)}." if name
                        else f"Say which chama: {', '.join(names)}.")
    detail = chama_detail(chosen, timezone.localdate())
    members = [{"name": m["full_name"], "role": m["role_label"], "active": m["active"], "joined": str(m["joined_on"]),
                "left": str(m["left_on"]) if m["left_on"] else None, "paid_in": _money(m["paid_in"]), "unpaid": _money(m["unpaid"]),
                "late": _money(m["late"]), "fines_owed": _money(m["fines_owed"]), "received": _money(m["received"]),
                "next_turn": str(m["next_turn"]["date"]) if m.get("next_turn") else None,
                "this_period": m["this_period"]["status"] if m.get("this_period") else None} for m in detail["members"]]
    money = {k: _money(v) for k, v in detail["money"].items()}
    # Whose turn it is, on which day and how much they receive: the full amount the turn collects, and what is in so far.
    full_turn = detail["contribution_amount"] * detail["periods_per_round"] * sum(1 for m in detail["members"] if m["active"])
    turns = [{"turn": t["round"], "date": str(t["date"]), "weekday": t["date"].strftime("%A"), "member": t["member"] or "to be agreed",
              "status": t["status"].lower(), "receives": _money(t.get("expected") if t.get("expected") is not None else full_turn),
              "collected_so_far": _money(t.get("collected")) if t.get("collected") is not None else None}
             for t in detail["turns"] if t["status"] != "GIVEN"][:4]
    given = [{"turn": t["round"], "member": t["member"], "received": _money(t["amount"]), "on": str(t["paid_on"])}
             for t in detail["turns"] if t["status"] == "GIVEN"][-4:]
    return {"chama": detail["name"], "contribution": _money(detail["contribution_amount"]), "frequency": detail["frequency"],
            "contributions_per_turn": detail["periods_per_round"], "next_turns": turns, "turns_given": given,
            "payout_mode": detail["payout_mode"], "current_period": str(detail["current_period"]) if detail["current_period"] else None,
            "next_receiver": detail["next_receiver"]["full_name"] if detail.get("next_receiver") else None,
            "money": money, "members": members, "note": "ID numbers and phone numbers are kept on the Chama page, not shown here."}


def activity_log(ctx, args):
    from apps.core.models import AuditLog
    start, end = _period(args, default_days=7)
    rows = AuditLog.objects.filter(created_at__date__range=(start, end)).select_related("user")
    person = " ".join(str(args.get("person", "")).split())
    if person:
        rows = rows.filter(Q(user__first_name__icontains=person) | Q(user__last_name__icontains=person) | Q(user__username__icontains=person))
    action = str(args.get("action", "")).strip().upper()
    if action:
        rows = rows.filter(action__icontains=action)
    by_action = [{"action": row["action"], "times": row["n"]} for row in rows.values("action").annotate(n=Count("id")).order_by("-n")[:30]]
    by_person = [{"person": row["user__first_name"] or row["user__username"] or "System", "actions": row["n"]}
                 for row in rows.values("user__first_name", "user__username").annotate(n=Count("id")).order_by("-n")]
    latest = [{"when": timezone.localtime(a.created_at).strftime("%Y-%m-%d %H:%M"), "who": _customer_name(a.user) if a.user_id else "System",
               "action": a.action, "record": a.object_type} for a in rows.order_by("-created_at")[:_limit(args, 25, 100)]]
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "total_actions": rows.count(), "by_action": by_action,
            "by_person": by_person, "latest": latest}


def platform_help(ctx, args):
    from .retrieval import retrieve
    question = " ".join(str(args.get("question", "")).split())
    if not question:
        raise ToolError("Give the question to look up in the help centre.")
    return {"passages": [{"article": p.article, "section": p.heading, "text": p.text} for p in retrieve(question)[:4]]}


# Registry --------------------------------------------------------------------------------------

def _schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


PERIOD = {"start_date": {"type": "string", "description": "First day, YYYY-MM-DD, or \"beginning\" for since the business started. "
                                                          "Defaults to 30 days before end_date."},
          "end_date": {"type": "string", "description": "Last day, YYYY-MM-DD. Defaults to today."}}
LIMIT = {"limit": {"type": "integer", "description": "Maximum rows to list."}}

# name: (handler, description, input schema, required permission, required module or None)
TOOLS = {
    "business_overview": (business_overview, "The business's profile: name, type, currency, today's date, branches, enabled modules, "
                          "subscription, the asking person's role and catalogue size. Call first when you need context.",
                          _schema(), None, None),
    "find_products": (find_products, "Search products and services by name, SKU, barcode, brand or category. Returns price, "
                      "stock on hand and available, reorder levels and (if allowed) cost and margin.",
                      _schema({"query": {"type": "string"}, **LIMIT}, ["query"]), "catalog.view_product", None),
    "stock_levels": (stock_levels, "Current stock across the catalogue: totals, and items that are low, out of stock, overstocked "
                     "(over 1.5× target) or all, with suggested reorder quantities.",
                     _schema({"view": {"type": "string", "enum": ["low", "out", "overstock", "all"]}, "category": {"type": "string"}, **LIMIT}),
                     "inventory.view_stockbalance", "inventory"),
    "inventory_analysis": (inventory_analysis, "Scientific stock analysis over the last N days: ABC (Pareto) classes, top sellers, "
                           "days of cover, items running out within 14 days, dead stock, sell-through, and (if allowed) turnover and GMROI.",
                           _schema({"days": {"type": "integer", "description": "Look-back window in days (default 90)."}, **LIMIT}),
                           "inventory.view_stockbalance", "inventory"),
    "sales_summary": (sales_summary, "Completed sales in a period: totals, average sale, discounts and (if allowed) gross profit, "
                      "grouped by day, week, month, hour, weekday, product, category, channel, payment_method or staff.",
                      _schema({**PERIOD, "group_by": {"type": "string", "enum": ["day", "week", "month", "hour", "weekday", "product", "category",
                                                                                "channel", "payment_method", "staff"]}, **LIMIT}),
                      "commerce.view_sale", "pos"),
    "sales_statistics": (sales_statistics, "Statistical analysis of daily sales: mean, median, standard deviation, coefficient of "
                         "variation, least-squares trend with R², weekday pattern, unusual days (z-scores), comparison with the "
                         "previous period and a forecast with a 95% range. Default period: the last 90 days.",
                         _schema({**PERIOD, "metric": {"type": "string", "enum": ["revenue", "sales_count", "gross_profit"]},
                                  "forecast_days": {"type": "integer"}}), "commerce.view_sale", "pos"),
    "stock_movements": (stock_movements, "Stock movements and adjustments in a period (optionally one SKU): by type, by reason "
                        "(damaged, lost, count variance...), shrinkage rate and the latest adjustments with who made them.",
                        _schema({**PERIOD, "sku": {"type": "string"}, **LIMIT}), "inventory.view_movement", "inventory"),
    "financial_summary": (financial_summary, "Profit and loss from the posted books for a period, per business unit (shop, services, "
                          "M-Pesa): revenue, cost of sales, expenses, gross and net profit, money received, monthly revenue and its statistics.",
                          _schema(PERIOD), "accounting.view_cashentry", "reports"),
    "expense_analysis": (expense_analysis, "Expenses in a period from the posted books: total, by category, by business unit, by month, "
                         "and as a share of revenue.", _schema(PERIOD), "accounting.view_expense", "expenses"),
    "service_jobs": (service_jobs, "Service desk (jobs) in a period: jobs by status, value completed, average minutes to complete, "
                     "overdue jobs, the top services, and each job (customer, phone, services, amounts, payment, who served, "
                     "when opened and completed).", _schema({**PERIOD, **LIMIT}), "cyber.view_cyberjob", "services"),
    "mpesa_summary": (mpesa_summary, "M-Pesa agency in a period: transactions by type, commission, reconciliation cash and float "
                      "variances; each shift (open now, and closed ones in the period) with operator, opening and current cash and float, "
                      "totals by type and its transactions; and the latest transactions, each with time, type, amount, customer name and "
                      "phone, M-Pesa code, who posted it and whether it was reversed. Use this, not the activity log, for M-Pesa questions.",
                      _schema({**PERIOD, **LIMIT}), "mpesa.view_mpesasession", "mpesa"),
    "agency_commission": (agency_commission, "M-Pesa agency month by month: Safaricom commission earned, agency running costs and profit; "
                          "a month whose commission is not recorded yet; each outlet's money in operation now; recent commission entries "
                          "(including undone ones and why).", _schema({"months": {"type": "integer"}, **LIMIT}), "mpesa.view_mpesacommissionentry", "mpesa"),
    "money_position": (money_position, "Where the money is right now and what the business is worth: shop drawer, till and bank, M-Pesa "
                       "agency cash and float, investments, money lent out, commission owed, customers owing, stock at cost, minus "
                       "suppliers and unpaid running costs; plus recent net worth history.", _schema(), "accounting.view_profit", "reports"),
    "money_owed_to_business": (money_owed_to_business, "Who owes the business money now: customers with unpaid sales (by customer, "
                               "by age, overdue), refunds owed to customers, and (if allowed) money lent out and loan status.",
                               _schema(LIMIT), "accounting.view_cashentry", None),
    "money_business_owes": (money_business_owes, "What the business owes now: suppliers for stock received and not paid, and unpaid "
                            "running-cost bills with due dates.", _schema(LIMIT), "accounting.view_supplierpurchase", None),
    "purchases_and_suppliers": (purchases_and_suppliers, "Stock bought from suppliers in a period: total, by supplier (bought and "
                                "still owed) and the latest purchases.", _schema({**PERIOD, **LIMIT}), "accounting.view_supplierpurchase", None),
    "find_sales": (find_sales, "Look up one sale by its number, or a customer's sales by name or phone: items, payments, who sold it, "
                   "what is still owed, and the customer's history.",
                   _schema({"sale_number": {"type": "string"}, "customer": {"type": "string"}, **LIMIT}), "commerce.view_sale", None),
    "top_customers": (top_customers, "Customers in a period: top spenders, new versus returning, and walk-in sales. Default: last 90 days.",
                      _schema({**PERIOD, **LIMIT}), "commerce.view_sale", None),
    "investments": (investments, "Investments such as money market funds: value now, money put in and taken out, interest and fees, the yearly rate now (CIC's published rate when followed) and what the money earns a day, month and year after tax.",
                    _schema(), "accounting.view_investment", "investments"),
    "chamas": (chamas, "The chamas (savings groups) the business manages: members, contribution, money held, this period's "
               "collection, late members and whose turn is next.", _schema(), "chama.view_chama", "chama"),
    "chama_members": (chama_members, "One chama's members (by chama name; optional when there is only one): role, joined, paid in, "
                      "unpaid, late, fines owed, money received, next turn and this period's status, plus the chama's money and "
                      "who receives next.", _schema({"chama": {"type": "string"}}), "chama.view_chama", "chama"),
    "activity_log": (activity_log, "Who did what and when (the audit trail): actions by type and person, and the latest actions. "
                     "Filter by person or action word (e.g. SALE, REVERSE, ADJUST). Default: last 7 days.",
                     _schema({**PERIOD, "person": {"type": "string"}, "action": {"type": "string"}, **LIMIT}), "core.view_auditlog", None),
    "platform_help": (platform_help, "How to do something in the software itself (steps, pages, settings). Search the help centre.",
                      _schema({"question": {"type": "string"}}, ["question"]), None, None),
}

from . import platform_tools  # noqa: E402  (registered after the business tools)

TOOLS.update({
    "platform_overview": (platform_tools.platform_overview, "Platform administrator only: totals across every registered business "
                          "(on trial, paying, ended, expiring soon, complimentary, by plan), platform revenue, sign-ups by month and "
                          "recent subscription payments.", _schema(), platform_tools.PLATFORM, None),
    "platform_businesses": (platform_tools.platform_businesses, "Platform administrator only: the registered businesses with owner "
                            "and contact, plan, subscription status and days left, payments to the platform, staff, branches, tools "
                            "enabled and how active each is (last activity, actions and sales count in 30 days). Filter by status or "
                            "search by name, type, owner, phone or email.",
                            _schema({"status": {"type": "string", "enum": ["all", "trial", "paying", "ended", "expiring_soon", "complimentary",
                                                                         "inactive"]}, "query": {"type": "string"}, **LIMIT}),
                            platform_tools.PLATFORM, None),
    "platform_admin_help": (platform_tools.platform_admin_help, "Platform administrator only: how to run the platform (plans, trials, "
                            "changing or extending subscriptions, manual payments, M-Pesa billing settings, AI assistant setup).",
                            _schema({"question": {"type": "string"}}, ["question"]), platform_tools.PLATFORM, None),
})


def available(ctx):
    """The tools this person may use in this business: (name, description, schema)."""
    return [(name, description, schema) for name, (_, description, schema, permission, module) in TOOLS.items()
            if ctx.can(permission) and (module is None or module in ctx.modules)]


def run(ctx, name, args):
    """(result text, is_error). Permission is checked again here: the model can only call offered tools."""
    entry = TOOLS.get(name)
    if entry is None or name not in {n for n, _, _ in available(ctx)}:
        return json.dumps({"error": f"The tool {name!r} is not available to this person."}), True
    if not isinstance(args, dict):
        return json.dumps({"error": "Tool input must be a JSON object."}), True
    try:
        result = entry[0](ctx, args)
    except ToolError as exc:
        return json.dumps({"error": str(exc)}), True
    text = json.dumps(result, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '..."} (result cut short: ask for a smaller limit or period)'
    return text, False
