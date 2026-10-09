import { useEffect, useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { BarList, ColumnChart, LineChart, SERIES } from "../../components/charts/Charts";
import { getCyberAnalysis } from "./api";

const asDate = (value) => new Date(`${value}T12:00:00`);
const dayLabel = { header: "Day", short: (p) => asDate(p.date).toLocaleDateString(undefined, { day: "numeric", month: "short" }),
  full: (p) => asDate(p.date).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) };
const hour = (h) => new Date(2026, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });

// How the service desk has been doing: income and jobs each day, the services that bring the most, the busiest hours
// and how long customers wait for a job. Only completed jobs whose sale still stands count.
export function CyberAnalysis({ refreshKey }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    getCyberAnalysis(days).then((found) => { if (live) { setData(found); setError(""); } }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [days, refreshKey]);
  const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  const count = (value) => Number(value || 0).toLocaleString();
  const points = (data?.days || []).map((d) => ({ ...d, income: Number(d.income), profit: d.profit == null ? null : Number(d.profit) }));
  const jobs = points.reduce((sum, d) => sum + d.jobs, 0);
  const income = points.reduce((sum, d) => sum + d.income, 0);
  const busiest = data?.hours?.length ? data.hours.reduce((a, b) => (b.count > a.count ? b : a)) : null;
  return (
    <section className="businessAnalysis mpesaAnalysis" aria-labelledby="cyber-analysis-title">
      <div className="sectionHeading">
        <h2 id="cyber-analysis-title">Service analysis</h2>
        <label>Period
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={365}>Last 12 months</option>
          </select>
        </label>
      </div>
      {error && <p className="formNotice formNoticeError" role="alert">Could not load the analysis: {error}</p>}
      {data && !jobs && <p className="muted">No completed services in these days yet.</p>}
      {data && jobs > 0 && <>
        <p className="muted">{count(jobs)} services done for {money(income)}, about {money(income / jobs)} each.</p>
        <div className="chartGrid2">
          <LineChart title="Income each day" points={points} label={dayLabel} format={money}
            note={points.some((p) => p.profit != null) ? "Profit is income less the materials used." : undefined}
            series={[{ key: "income", label: "Income", area: true }, { key: "profit", label: "Profit", color: SERIES[2] }]} />
          <ColumnChart title="Services done each day" points={points} label={dayLabel} format={count} series={[{ key: "jobs", label: "Services done" }]} />
          <BarList title="Services that bring the most" note="Income by service." format={money} empty="No services done in these days."
            rows={data.services.map((s) => ({ label: s.name, value: Number(s.income), detail: `${Number(s.units).toLocaleString()} units` }))} />
          {data.hours.length > 0 && <ColumnChart title="Busiest hours" points={data.hours} format={count}
            label={{ header: "Hour", short: (p) => hour(p.hour), full: (p) => `${hour(p.hour)} – ${hour(p.hour + 1)}` }}
            note={busiest ? `Most services are finished between ${hour(busiest.hour)} and ${hour(busiest.hour + 1)}.` : undefined}
            series={[{ key: "count", label: "Services done" }]} />}
          <ColumnChart title="How long customers wait" points={data.waits} format={count} note="From taking in a job to finishing it."
            label={{ header: "Wait", short: (p) => p.label.replace(" minutes", " min").replace("15 min to 1 hour", "15–60 min"), full: (p) => p.label }}
            series={[{ key: "count", label: "Services", color: SERIES[1] }]} />
        </div>
      </>}
    </section>
  );
}
