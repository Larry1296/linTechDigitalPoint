"""Statistics for the business assistant, computed here so every figure the AI quotes is exact.

The AI explains the numbers; it never does the arithmetic. Everything is plain Python on small
series (one value per day, one row per product), so no numeric libraries are needed.
"""
import math
from datetime import timedelta
from decimal import Decimal

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _f(value):
    return float(value or 0)


def r(value, places=2):
    """A float rounded for display; None stays None."""
    return None if value is None else round(float(value), places)


def mean(values):
    return sum(values) / len(values) if values else 0.0


def stdev(values):
    """Sample standard deviation (n - 1)."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def linear_trend(values):
    """Least-squares line through (day index, value): slope per day, intercept and R²."""
    n = len(values)
    if n < 2:
        return {"slope_per_day": 0.0, "intercept": values[0] if values else 0.0, "r_squared": 0.0}
    xs = range(n)
    mx, my = (n - 1) / 2, mean(values)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    slope = sxy / sxx
    intercept = my - slope * mx
    total = sum((y - my) ** 2 for y in values)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, values))
    return {"slope_per_day": slope, "intercept": intercept, "r_squared": 1 - residual / total if total else 0.0}


def daily_series(totals_by_day, start, end):
    """[(date, value)] for every day from start to end, with 0 on days without records."""
    days, day = [], start
    while day <= end:
        days.append((day, _f(totals_by_day.get(day))))
        day += timedelta(days=1)
    return days


def describe_series(series, forecast_days=7):
    """Descriptive statistics, trend, weekday pattern, unusual days and a short forecast for a daily series."""
    values = [v for _, v in series]
    n = len(values)
    if not n:
        return {"days": 0}
    m, sd = mean(values), stdev(values)
    trend = linear_trend(values)
    half = n // 2
    first, second = sum(values[:half]), sum(values[half:])
    by_weekday = {}
    for day, value in series:
        by_weekday.setdefault(day.weekday(), []).append(value)
    weekday_avg = {WEEKDAYS[k]: r(mean(v)) for k, v in sorted(by_weekday.items())}
    anomalies = []
    if sd > 0:
        for day, value in series:
            z = (value - m) / sd
            if abs(z) >= 2:
                anomalies.append({"date": day.isoformat(), "value": r(value), "z_score": r(z), "kind": "unusually high" if z > 0 else "unusually low"})
    # Forecast: the trend line continued, scaled by each weekday's typical share of an average day.
    # The ±1.96 × residual spread gives a rough 95% range; with few days it is wide on purpose.
    residuals = [v - (trend["intercept"] + trend["slope_per_day"] * i) for i, v in enumerate(values)]
    spread = stdev(residuals) if n > 2 else sd
    forecast = []
    last_day = series[-1][0]
    for step in range(1, forecast_days + 1):
        day = last_day + timedelta(days=step)
        base = trend["intercept"] + trend["slope_per_day"] * (n - 1 + step)
        factor = (mean(by_weekday.get(day.weekday(), [])) / m) if m and n >= 14 else 1.0
        expected = max(base * factor, 0.0)
        forecast.append({"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "expected": r(expected),
                         "low": r(max(expected - 1.96 * spread, 0.0)), "high": r(expected + 1.96 * spread)})
    zero_days = sum(1 for v in values if v == 0)
    return {
        "days": n, "total": r(sum(values)), "mean_per_day": r(m), "median_per_day": r(sorted(values)[n // 2] if n % 2 else mean(sorted(values)[n // 2 - 1:n // 2 + 1])),
        "std_dev": r(sd), "coefficient_of_variation": r(sd / m, 3) if m else None,
        "min": r(min(values)), "max": r(max(values)), "days_without_activity": zero_days,
        "trend": {"slope_per_day": r(trend["slope_per_day"]), "r_squared": r(trend["r_squared"], 3),
                  "direction": "rising" if trend["slope_per_day"] > 0 else "falling" if trend["slope_per_day"] < 0 else "flat",
                  "strength": "strong" if trend["r_squared"] >= 0.5 else "moderate" if trend["r_squared"] >= 0.2 else "weak"},
        "second_half_vs_first_half_pct": r((second - first) / first * 100) if first else None,
        "average_by_weekday": weekday_avg,
        "unusual_days": anomalies[:10],
        "forecast_next_days": forecast,
    }


def abc_classes(rows, key="revenue"):
    """Pareto (ABC) classes: A = items making the first 80% of the total, B = the next 15%, C = the rest."""
    ranked = sorted(rows, key=lambda row: _f(row[key]), reverse=True)
    total = sum(_f(row[key]) for row in ranked)
    running = 0.0
    for row in ranked:
        share = _f(row[key]) / total if total else 0.0
        before = running
        running += share
        row["share_pct"] = r(share * 100)
        row["abc_class"] = "A" if before < 0.80 else "B" if before < 0.95 else "C"
    return ranked


def safe_div(a, b):
    a, b = Decimal(str(a or 0)), Decimal(str(b or 0))
    return None if b == 0 else a / b
