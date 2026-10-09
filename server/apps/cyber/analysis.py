"""How the service desk has been doing, for the Services dashboard's Analysis: income and jobs day by day, the services
that bring the most, the busiest hours and how long jobs take. Only completed jobs whose sale still stands count, as
for income anywhere else (income.py)."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import CyberJob, CyberJobLine

ZERO = Decimal("0")
WAITS = [(timedelta(minutes=15), "Under 15 minutes"), (timedelta(hours=1), "15 minutes to 1 hour"), (timedelta(hours=4), "1 to 4 hours"),
         (timedelta(days=1), "Same day"), (None, "Longer")]


def analysis(days=30, show_profit=False):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    jobs = list(CyberJob.objects.filter(status="COMPLETED", sale__status="COMPLETED", completed_at__date__gte=start)
                .select_related("sale").only("pk", "total", "created_at", "completed_at", "sale__gross_profit"))
    by_day = {start + timedelta(days=n): {"date": start + timedelta(days=n), "income": ZERO, "jobs": 0, "profit": ZERO if show_profit else None}
              for n in range(days)}
    hours = defaultdict(int)
    waits = defaultdict(int)
    for job in jobs:
        done = timezone.localtime(job.completed_at)
        day = by_day.get(done.date())
        if day is None:
            continue
        day["income"] += job.total
        day["jobs"] += 1
        if show_profit:
            day["profit"] += job.sale.gross_profit or ZERO
        hours[done.hour] += 1
        took = job.completed_at - job.created_at
        waits[next(label for limit, label in WAITS if limit is None or took <= limit)] += 1
    services = (CyberJobLine.objects.filter(job__in=[job.pk for job in jobs]).values("variant__product__name")
                .annotate(income=Sum("line_total"), units=Sum("quantity")).order_by("-income"))
    busy = sorted(hours)
    return {"days": list(by_day.values()),
            "services": [{"name": row["variant__product__name"], "income": row["income"], "units": row["units"]} for row in services],
            "hours": [{"hour": hour, "count": hours[hour]} for hour in range(busy[0], busy[-1] + 1)] if busy else [],
            "waits": [{"label": label, "count": waits[label]} for _, label in WAITS]}
