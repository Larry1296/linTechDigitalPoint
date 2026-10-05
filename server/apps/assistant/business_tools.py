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
MAX_DAYS = 730


class ToolError(Exception):
    """A problem with the tool's input, reported back to the model so it can correct itself."""


class Context:
    """Who is asking, in which business: decides which tools and fields are available."""

    def __init__(self, user, organization, branch=None):
        self.user, self.organization, self.branch = user, organization, branch
        self.modules = set(effective_modules(organization))
        self.membership = membership_for(user)

    def can(self, permission):
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


def _period(args, default_days=30):
    today = timezone.localdate()
    end = _date(args["end_date"], "end_date") if args.get("end_date") else today
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
    if category:
        variants = variants.filter(Q(product__category__name__icontains=category) | Q(product__category__parent__name__icontains=category))
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
            row = {"product": _variant_label(v), "sku": v.sku, "category": v.product.category.name, "on_hand": _qty(on_hand),
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
            "previous_period_total": r(previous), "change_vs_previous_period_pct": r((current - float(previous)) / float(previous) * 100) if previous else None,
            "method": "Least-squares trend over daily totals (days without sales count as 0); unusual days have |z| ≥ 2; "
                      "forecast = trend continued × weekday pattern (with 14+ days of history), range ≈ 95%."}


def inventory_analysis(ctx, args):
    from apps.catalog.models import ProductVariant
    days = _limit({"limit": args.get("days", 90)}, 90, MAX_DAYS)
    end = timezone.localdate()
    start = end - timedelta(days=days - 1)
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
    result = {"period_days": days, "stock_items": len(ranked), "abc_summary": classes,
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


def service_jobs(ctx, args):
    from apps.cyber.models import CyberJob, CyberJobLine
    start, end = _period(args)
    jobs = CyberJob.objects.filter(created_at__date__range=(start, end)).exclude(sale__status="CANCELLED")
    by_status = {row["status"]: row["n"] for row in jobs.values("status").annotate(n=Count("id"))}
    done = jobs.filter(status="COMPLETED", started_at__isnull=False, completed_at__isnull=False)
    hours = [(j.completed_at - j.started_at).total_seconds() / 3600 for j in done.only("started_at", "completed_at")]
    top = [{"service": row["service_name"], "jobs": row["n"], "quantity": _qty(row["q"]), "value": _money(row["v"])}
           for row in CyberJobLine.objects.filter(job__in=jobs.filter(status="COMPLETED")).values("service_name")
           .annotate(n=Count("job", distinct=True), q=Sum("quantity"), v=Sum("line_total")).order_by("-v")[:_limit(args)]]
    overdue = CyberJob.objects.exclude(status__in=["COMPLETED", "CANCELLED"]).filter(due_at__lt=timezone.now()).count()
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "jobs_by_status": by_status,
            "completed_value": _money(jobs.filter(status="COMPLETED").aggregate(v=Sum("total"))["v"]),
            "average_hours_to_complete": r(sum(hours) / len(hours)) if hours else None, "open_jobs_overdue_now": overdue, "top_services": top}


def mpesa_summary(ctx, args):
    from apps.mpesa.models import MpesaCommissionEntry, MpesaReconciliation, MpesaSession, MpesaTransaction
    start, end = _period(args)
    tx = MpesaTransaction.objects.filter(occurred_at__date__range=(start, end), status="POSTED")
    by_type = [{"type": row["transaction_type"], "count": row["n"], "amount": _money(row["v"])}
               for row in tx.values("transaction_type").annotate(n=Count("id"), v=Sum("amount")).order_by("-v")]
    recs = MpesaReconciliation.objects.filter(created_at__date__range=(start, end))
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "transactions_by_type": by_type,
            "transactions": tx.count(), "commission_recorded": _money(MpesaCommissionEntry.objects.filter(period__range=(start, end)).aggregate(v=Sum("amount"))["v"]),
            "reconciliations": recs.count(), "cash_variance_total": _money(recs.aggregate(v=Sum("cash_variance"))["v"]),
            "float_variance_total": _money(recs.aggregate(v=Sum("float_variance"))["v"]),
            "sessions_open_now": MpesaSession.objects.filter(status="OPEN").count()}


def platform_help(ctx, args):
    from .retrieval import retrieve
    question = " ".join(str(args.get("question", "")).split())
    if not question:
        raise ToolError("Give the question to look up in the help centre.")
    return {"passages": [{"article": p.article, "section": p.heading, "text": p.text} for p in retrieve(question)[:4]]}


# Registry --------------------------------------------------------------------------------------

def _schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


PERIOD = {"start_date": {"type": "string", "description": "First day, YYYY-MM-DD. Defaults to 30 days before end_date."},
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
    "service_jobs": (service_jobs, "Service desk (jobs) in a period: jobs by status, value completed, average hours to complete, "
                     "overdue jobs and the top services.", _schema({**PERIOD, **LIMIT}), "cyber.view_cyberjob", "services"),
    "mpesa_summary": (mpesa_summary, "M-Pesa agency in a period: transactions by type, commission, reconciliation cash and float "
                      "variances, open sessions.", _schema(PERIOD), "mpesa.view_mpesasession", "mpesa"),
    "platform_help": (platform_help, "How to do something in the software itself (steps, pages, settings). Search the help centre.",
                      _schema({"question": {"type": "string"}}, ["question"]), None, None),
}


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
