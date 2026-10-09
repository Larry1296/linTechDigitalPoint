import { useEffect, useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { BarList, ColumnChart, LineChart, SERIES } from "../../components/charts/Charts";
import { getMpesaAnalysis } from "./api";

const asDate = (value) => new Date(`${value}T12:00:00`);
const dayLabel = { header: "Day", short: (p) => asDate(p.date).toLocaleDateString(undefined, { day: "numeric", month: "short" }),
  full: (p) => asDate(p.date).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) };
const hour = (h) => new Date(2026, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
const KIND = { deposits: "Deposits", withdrawals: "Withdrawals", airtime: "Airtime" };

// How the agency has been doing over its last working days (Sundays closed): the money through it, how many
// transactions, the commission they earned, the busiest hours, the usual sizes and which kind earns the most.
export function MpesaAnalysis({ refreshKey }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    getMpesaAnalysis(days).then((found) => { if (live) { setData(found); setError(""); } }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [days, refreshKey]);
  const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  const count = (value) => Number(value || 0).toLocaleString();
  const points = (data?.days || []).map((d) => ({ ...d, deposits: Number(d.deposits), withdrawals: Number(d.withdrawals), airtime: Number(d.airtime), commission: Number(d.commission) }));
  const busiest = data?.hours?.length ? data.hours.reduce((a, b) => (b.count > a.count ? b : a)) : null;
  const total = points.reduce((sum, d) => sum + d.count, 0);
  return (
    <section className="businessAnalysis mpesaAnalysis" aria-labelledby="mpesa-analysis-title">
      <div className="sectionHeading">
        <h2 id="mpesa-analysis-title">Agency analysis</h2>
        <label>Period
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            <option value={7}>Last 7 working days</option><option value={30}>Last 30 working days</option>
            <option value={60}>Last 60 working days</option><option value={90}>Last 90 working days</option>
          </select>
        </label>
      </div>
      {error && <p className="formNotice formNoticeError" role="alert">Could not load the analysis: {error}</p>}
      {data && !total && <p className="muted">No deposits, withdrawals or airtime in these days yet.</p>}
      {data && total > 0 && <>
        <p className="muted">{count(total)} transactions over {data.working_days} working days (Sundays closed).
          {data.unknown > 0 && ` ${count(data.unknown)} of them have commission not worked out yet, so the commission figures are a little low.`}</p>
        <div className="chartGrid2">
          <LineChart title="Money through the agency each day" points={points} label={dayLabel} format={money}
            note="Customers' money, not income: what was deposited, withdrawn and sold as airtime."
            series={[{ key: "deposits", label: "Deposits" }, { key: "withdrawals", label: "Withdrawals" }, { key: "airtime", label: "Airtime" }]} />
          <LineChart title="Commission earned each day" points={points} label={dayLabel} format={money}
            note="The agency's income: measured from your readings or worked out by the app."
            series={[{ key: "commission", label: "Commission", color: SERIES[2], area: true }]} />
          <ColumnChart title="Transactions each day" points={points} label={dayLabel} format={count}
            series={[{ key: "count", label: "Transactions" }]} />
          {data.hours.length > 0 && <ColumnChart title="Busiest hours" points={data.hours} format={count}
            label={{ header: "Hour", short: (p) => hour(p.hour), full: (p) => `${hour(p.hour)} – ${hour(p.hour + 1)}` }}
            note={busiest ? `Most transactions happen between ${hour(busiest.hour)} and ${hour(busiest.hour + 1)}: have enough cash and float ready then.` : undefined}
            series={[{ key: "count", label: "Transactions" }]} />}
          <ColumnChart title="Transaction sizes" points={data.sizes} format={count} note={`How many transactions of each size (${businessCurrency()}).`}
            label={{ header: "Size", short: (p) => p.label.replace("Up to ", "≤ ").replace("Over ", "> ").replace(" to ", "–"), full: (p) => p.label }}
            series={[{ key: "count", label: "Transactions", color: SERIES[1] }]} />
          <BarList title="Which transactions earn the commission" note="Commission by kind of transaction." format={money} color={SERIES[2]}
            rows={data.commission_by_kind.map((row) => ({ label: KIND[row.kind], value: Number(row.amount) }))} empty="No commission worked out yet." />
        </div>
      </>}
    </section>
  );
}
