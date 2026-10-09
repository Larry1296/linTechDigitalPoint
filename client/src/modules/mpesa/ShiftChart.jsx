import { useEffect, useRef, useState } from "react";
import { businessCurrency, businessTimeZone } from "../../core/organization/presentation";

const CUSTOMER = { CUSTOMER_DEPOSIT: "Deposit", CUSTOMER_WITHDRAWAL: "Withdrawal", AIRTIME_SALE: "Airtime" };
const clock = (value) => new Date(value).toLocaleTimeString([], { timeZone: businessTimeZone(), hour: "2-digit", minute: "2-digit" });
const whole = (value) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// The shift from opening to closing (now, while it is open): after each deposit, withdrawal and airtime sale, how many
// there had been and the commission they had earned. Reversed ones and their reversals are left out, as on the desk.
export function shiftSeries(transactions, openedAt, closedAt) {
  const reversed = new Set(transactions.filter((t) => t.reversal_of).map((t) => t.reversal_of));
  const rows = transactions.filter((t) => CUSTOMER[t.transaction_type] && !reversed.has(t.id))
    .sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at));
  const start = new Date(openedAt).getTime();
  const points = [{ time: start, count: 0, commission: 0, unknown: 0, kind: "open" }];
  for (const t of rows) {
    const last = points[points.length - 1];
    const earned = t.commission_earned == null ? null : Number(t.commission_earned);
    points.push({ time: Math.max(start, new Date(t.occurred_at).getTime()), count: last.count + 1, commission: last.commission + (earned ?? 0),
      unknown: last.unknown + (earned == null ? 1 : 0), kind: "transaction", entry: t, earned });
  }
  const last = points[points.length - 1];
  const end = Math.max(last.time, closedAt ? new Date(closedAt).getTime() : Date.now());
  points.push({ ...last, time: end, kind: closedAt ? "close" : "now", entry: undefined, earned: undefined });
  return points;
}

// Clean axis steps: 0 and a few round numbers covering the largest value.
function niceTicks(max) {
  if (max <= 0) return [0, 1];
  const raw = max / 3;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw);
  const ticks = [];
  for (let v = 0; v < max + step; v += step) ticks.push(v);
  return ticks;
}

// Round times along the bottom, as many as fit the width without touching (about 76px each).
function timeTicks(start, end, most) {
  const span = end - start;
  const minute = 60000;
  const step = [15, 30, 60, 120, 180, 240, 360, 720, 1440].map((m) => m * minute).find((s) => span / s <= most) || 1440 * minute;
  const ticks = [];
  for (let t = Math.ceil(start / step) * step; t <= end; t += step) ticks.push(t);
  return ticks;
}

function useWidth(ref) {
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const measure = () => setWidth(element.clientWidth || 640);
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

const MARGIN = { left: 58, right: 18, top: 14 };

// One panel: a step line (a total only changes when a transaction happens) over a light wash, the crosshair when hovered.
function Panel({ points, field, width, height, x, color, money, axis, ticksX, active, label }) {
  const bottom = axis ? 26 : 8;
  const ticks = niceTicks(Math.max(...points.map((p) => p[field])));
  const top = ticks[ticks.length - 1];
  const y = (v) => MARGIN.top + (height - MARGIN.top - bottom) * (1 - v / top);
  const base = y(0);
  let line = `M${x(points[0].time)},${y(points[0][field])}`;
  for (const p of points.slice(1)) line += `H${x(p.time)}V${y(p[field])}`;
  const end = points[points.length - 1];
  const area = `${line}V${base}H${x(points[0].time)}Z`;
  const hovered = active == null ? null : points[active];
  return (
    <svg className="shiftChartPanel" width={width} height={height} role="img" aria-label={label}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} className="shiftChartGrid" />
          <text x={MARGIN.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="shiftChartTick">{money ? whole(t) : t}</text>
        </g>
      ))}
      {axis && ticksX.map((t) => (
        <text key={t} x={x(t)} y={height - 6} textAnchor="middle" className="shiftChartTick">{clock(t)}</text>
      ))}
      <path d={area} fill={color} opacity="0.1" />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(end.time)} cy={y(end[field])} r="4.5" fill={color} className="shiftChartDot" />
      {hovered && <>
        <line x1={x(hovered.time)} x2={x(hovered.time)} y1={MARGIN.top} y2={base} className="shiftChartCrosshair" />
        <circle cx={x(hovered.time)} cy={y(hovered[field])} r="5" fill={color} className="shiftChartDot" />
      </>}
    </svg>
  );
}

function Tooltip({ point }) {
  const title = point.kind === "open" ? "Shift opened" : point.kind === "close" ? "Shift closed" : point.kind === "now" ? "Now" : CUSTOMER[point.entry.transaction_type];
  return (
    <>
      <b>{clock(point.time)} · {title}</b>
      {point.entry && <span>{businessCurrency()} {whole(point.entry.amount)} · commission {point.earned == null
        ? "not worked out yet" : `${point.entry.commission_source === "learned" ? "≈ " : ""}${businessCurrency()} ${whole(point.earned)}`}</span>}
      <span>So far: {point.count} {point.count === 1 ? "transaction" : "transactions"}, {businessCurrency()} {whole(point.commission)} commission</span>
    </>
  );
}

// How a shift went, from opening to closing: transactions so far and the commission they earned, as two charts on one
// time line (two different measures never share an axis). Hover or use the arrow keys to read any moment; the same
// figures are in the table underneath. Kept with the shift, so a past shift shows its chart when it is opened again.
export function ShiftChart({ transactions, openedAt, closedAt }) {
  const box = useRef(null);
  const width = useWidth(box);
  const [active, setActive] = useState(null);
  const points = shiftSeries(transactions, openedAt, closedAt);
  const first = points[0].time;
  const last = points[points.length - 1].time;
  const span = Math.max(last - first, 60000);
  const x = (t) => MARGIN.left + (width - MARGIN.left - MARGIN.right) * ((t - first) / span);
  const ticksX = timeTicks(first, first + span, Math.max(2, Math.floor((width - MARGIN.left - MARGIN.right) / 76)));
  const end = points[points.length - 1];
  const nearest = (event) => {
    const rect = box.current.getBoundingClientRect();
    const time = first + ((event.clientX - rect.left - MARGIN.left) / (width - MARGIN.left - MARGIN.right)) * span;
    let best = 0;
    points.forEach((p, i) => { if (Math.abs(p.time - time) <= Math.abs(points[best].time - time)) best = i; });
    setActive(best);
  };
  const keys = (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const at = active ?? points.length - 1;
    setActive(event.key === "Home" ? 0 : event.key === "End" ? points.length - 1
      : Math.min(points.length - 1, Math.max(0, at + (event.key === "ArrowRight" ? 1 : -1))));
  };
  const hovered = active == null ? null : points[active];
  const transactionsOnly = points.filter((p) => p.kind === "transaction");
  return (
    <figure className="shiftChart">
      <figcaption>
        <div>
          <h3>How the shift went</h3>
          <p className="muted">{clock(first)} – {closedAt ? clock(last) : "now"}</p>
        </div>
        <dl>
          <div><dt><i className="shiftChartKey transactions" />Transactions</dt><dd>{end.count}</dd></div>
          <div><dt><i className="shiftChartKey commission" />Commission</dt><dd>{businessCurrency()} {whole(end.commission)}</dd></div>
        </dl>
      </figcaption>
      {end.unknown > 0 && <p className="muted shiftChartNote">{end.unknown} {end.unknown === 1 ? "transaction's" : "transactions'"} commission is not worked out yet, so not in the line.</p>}
      <div className="shiftChartPlot" ref={box} tabIndex={0} aria-label="Shift chart: use the left and right arrow keys to move between transactions"
        onPointerMove={nearest} onPointerLeave={() => setActive(null)} onKeyDown={keys} onBlur={() => setActive(null)}>
        <p className="shiftChartTitle">Transactions so far</p>
        <Panel points={points} field="count" width={width} height={120} x={x} color="var(--chart-transactions)" ticksX={ticksX} active={active}
          label={`Transactions so far: ${end.count} by ${clock(last)}`} />
        <p className="shiftChartTitle">Commission earned so far ({businessCurrency()})</p>
        <Panel points={points} field="commission" width={width} height={146} x={x} color="var(--chart-commission)" money axis ticksX={ticksX}
          active={active} label={`Commission earned so far: ${businessCurrency()} ${whole(end.commission)} by ${clock(last)}`} />
        {hovered && (
          <div className={`shiftChartTooltip${width < 480 ? " docked" : ""}`} role="status"
            style={width < 480 ? undefined : x(hovered.time) > width / 2 ? { right: width - x(hovered.time) + 12 } : { left: x(hovered.time) + 12 }}>
            <Tooltip point={hovered} />
          </div>
        )}
      </div>
      {transactionsOnly.length > 0 && (
        <details className="shiftChartTable">
          <summary>Show as a table</summary>
          <table>
            <thead><tr><th scope="col">Time</th><th scope="col">Transaction</th><th scope="col">Amount</th><th scope="col">Commission</th><th scope="col">Commission so far</th></tr></thead>
            <tbody>{transactionsOnly.map((p) => (
              <tr key={p.entry.id}>
                <th scope="row">{clock(p.time)}</th>
                <td>{CUSTOMER[p.entry.transaction_type]}</td>
                <td>{whole(p.entry.amount)}</td>
                <td>{p.earned == null ? "—" : `${p.entry.commission_source === "learned" ? "≈ " : ""}${whole(p.earned)}`}</td>
                <td>{whole(p.commission)}</td>
              </tr>
            ))}</tbody>
          </table>
        </details>
      )}
    </figure>
  );
}
