import { BarList, ColumnChart, LineChart, SERIES } from "../../components/charts/Charts";

const DAY = { weekday: "short", day: "numeric", month: "short", year: "numeric" };
const asDate = (value) => new Date(`${String(value).length === 7 ? `${value}-15` : value}T12:00:00`);
const dayLabel = { header: "Date", short: (p) => asDate(p.date).toLocaleDateString(undefined, { day: "numeric", month: "short" }), full: (p) => asDate(p.date).toLocaleDateString(undefined, DAY) };
const monthLabel = (key) => ({ header: "Month", short: (p) => asDate(p[key]).toLocaleDateString(undefined, { month: "short" }),
  full: (p) => asDate(p[key]).toLocaleDateString(undefined, { month: "long", year: "numeric" }) });
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// The last seven days' average sales, so a single big or quiet day does not hide the direction things are going.
export function withWeekAverage(points) {
  return points.map((p, i) => {
    if (i < 6) return { ...p, average: null };
    const week = points.slice(i - 6, i + 1).map((row) => Number(row.revenue) || 0);
    return { ...p, average: week.reduce((a, b) => a + b, 0) / 7 };
  });
}

// Average sales on each day of the week over the chosen dates (only days that came up, so a short range is fair).
export function byWeekday(points) {
  const totals = WEEKDAYS.map((name) => ({ day: name, total: 0, days: 0 }));
  for (const p of points) {
    const index = (asDate(p.date).getDay() + 6) % 7;
    totals[index].total += Number(p.revenue) || 0;
    totals[index].days += 1;
  }
  return totals.filter((row) => row.days).map((row) => ({ day: row.day, average: row.total / row.days }));
}

// The business at a glance, for the dates picked above it: how sales moved day by day, where they came from, what
// sold best, where the money went, the busiest days, and the last twelve months. Each chart has its numbers underneath.
export function BusinessAnalysis({ data, money }) {
  const performance = data.performance;
  if (!performance?.points?.length) return null;
  const daily = performance.granularity === "day";
  const points = daily ? withWeekAverage(performance.points) : performance.points;
  const label = daily ? dayLabel : monthLabel("date");
  const profitShown = points.some((p) => p.profit != null);
  const items = (data.top_items || []).map((item) => ({ label: item.name, value: Number(item.sales) || 0, detail: `${Number(item.quantity).toLocaleString()} sold` }));
  const costs = Object.values((data.expense_breakdown || []).reduce((all, row) => {
    all[row.category] = { label: row.category, value: (all[row.category]?.value || 0) + Number(row.amount) };
    return all;
  }, {}));
  const weekdays = daily ? byWeekday(points) : [];
  const months = (data.financial_trend || []).map((row) => ({ ...row, margin: row.profit != null && Number(row.sales) ? (Number(row.profit) / Number(row.sales)) * 100 : null }));
  const best = weekdays.length ? weekdays.reduce((a, b) => (b.average > a.average ? b : a)) : null;
  const period = `${data.period_summary.start} to ${data.period_summary.end}`;
  return (
    <section className="businessAnalysis" aria-labelledby="analysis-title">
      <h2 id="analysis-title">Analysis</h2>
      <p className="muted">For {period}. Hover over a chart, or select it and use the arrow keys, to read any day; each chart's numbers are underneath it.</p>
      <div className="chartGrid2">
        <LineChart title={daily ? "Sales each day" : "Sales each month"} points={points} label={label} format={money}
          note={daily && points.length >= 7 ? "The dashed line is the average of the last seven days: it shows which way sales are going." : undefined}
          series={[{ key: "revenue", label: "Sales", area: true }, ...(daily && points.length >= 7 ? [{ key: "average", label: "7-day average", dashed: true, color: "var(--muted)" }] : [])]} />
        {profitShown && <LineChart title="Sales, running costs and profit" points={points} label={label} format={money}
          note="Below zero means a loss on that day."
          series={[{ key: "revenue", label: "Sales" }, { key: "expenses", label: "Running costs" }, { key: "profit", label: "Profit or loss" }]} />}
        <BarList title="Best sellers" note="Products by what they sold for, after returns." rows={items} format={money} empty="No products sold in these dates." />
        {profitShown && <BarList title="Where the running costs went" note="Running costs by type." rows={costs} format={money} color={SERIES[1]} empty="No running costs in these dates." />}
        {weekdays.length > 1 && <ColumnChart title="Busiest days of the week" points={weekdays} label={{ header: "Day", short: (p) => p.day.slice(0, 3), full: (p) => p.day }}
          format={money} note={best ? `On average, ${best.day} brings the most sales.` : undefined} series={[{ key: "average", label: "Average sales" }]} />}
      </div>
      {months.length > 0 && <div className="chartGrid2 analysisMonths">
        <ColumnChart title="The last twelve months" points={months} label={monthLabel("month")} format={money}
          note={profitShown ? "Columns below zero are months that made a loss." : undefined}
          series={[{ key: "sales", label: "Sales" }, { key: "expenses", label: "Running costs" }, { key: "profit", label: "Profit or loss" }]} />
        {months.some((m) => m.margin != null) && <LineChart title="Profit kept from each 100 of sales" points={months} label={monthLabel("month")}
          format={(value) => `${Number(value).toFixed(0)}%`} tick={(value) => `${value}%`} note="The profit margin, month by month: the higher, the more of each sale you keep."
          series={[{ key: "margin", label: "Profit margin", color: SERIES[2], area: true }]} />}
      </div>}
    </section>
  );
}
