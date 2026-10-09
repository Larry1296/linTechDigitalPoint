import { useEffect, useRef, useState } from "react";
import "./charts.css";

// Charts for the dashboards, drawn as plain SVG so they follow the app's theme and need nothing extra in the browser.
// One rulebook for all of them: a single value axis (two different measures get two charts, never two axes), thin
// marks, quiet gridlines, series colours in a fixed order checked for colour blindness in both themes, a legend
// whenever there is more than one series, hover or arrow keys to read any point, and the same numbers as a table.

// Series colours, in this order. Each is a CSS variable with its own light and dark step (charts.css).
export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];

export function useWidth(ref, fallback = 640) {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const measure = () => setWidth(element.clientWidth || fallback);
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, fallback]);
  return width;
}

// Round steps for the value axis, up to above the highest value. Below zero (losses) it goes to the next round step,
// or, when the losses are small next to the rest, just below the lowest so the chart is not half empty.
export function niceScale(values) {
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  if (low === high) return { ticks: [0, 1], min: 0, max: 1 };
  const raw = (high - low) / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw);
  const max = Math.ceil(high / step) * step;
  const min = -low >= step / 4 || high === 0 ? Math.floor(low / step) * step : low * 1.2;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6 || 0);  // never "-0"
  return { ticks, min, max };
}

// Short axis figures: 1,250 · 12.5K · 4.2M.
export const compact = (value) => {
  const n = Number(value);
  const size = Math.abs(n);
  if (size >= 1e6) return `${(n / 1e6).toFixed(size >= 1e7 ? 0 : 1).replace(/\.0$/, "")}M`;
  if (size >= 1e4) return `${(n / 1e3).toFixed(size >= 1e5 ? 0 : 1).replace(/\.0$/, "")}K`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
};

function Legend({ series }) {
  if (series.length < 2) return null;
  return (
    <ul className="chartLegend">
      {series.map((s, i) => <li key={s.key}><i style={{ background: s.color || SERIES[i] }} className={s.dashed ? "dashed" : undefined} />{s.label}</li>)}
    </ul>
  );
}

function ChartTable({ points, series, label, format, caption }) {
  return (
    <details className="chartTable">
      <summary>See the numbers</summary>
      <div className="trendTable"><table>
        {caption && <caption>{caption}</caption>}
        <thead><tr><th scope="col">{label.header}</th>{series.map((s) => <th key={s.key} scope="col">{s.label}</th>)}</tr></thead>
        <tbody>{points.map((p, i) => (
          <tr key={i}><th scope="row">{label.full(p)}</th>{series.map((s) => <td key={s.key}>{p[s.key] == null ? "—" : format(p[s.key])}</td>)}</tr>
        ))}</tbody>
      </table></div>
    </details>
  );
}

function Tooltip({ title, rows, style, docked }) {
  return (
    <div className={`chartTooltip${docked ? " docked" : ""}`} role="status" style={docked ? undefined : style}>
      <b>{title}</b>
      {rows.map((row) => <span key={row.label}><i style={{ background: row.color }} />{row.label}<em>{row.value}</em></span>)}
    </div>
  );
}

// Keyboard reading shared by both charts: arrows move between points, Home and End jump to the ends.
function stepper(active, setActive, count) {
  return (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const at = active ?? count - 1;
    setActive(event.key === "Home" ? 0 : event.key === "End" ? count - 1 : Math.min(count - 1, Math.max(0, at + (event.key === "ArrowRight" ? 1 : -1))));
  };
}

const MARGIN = { top: 12, right: 16, bottom: 28 };

/**
 * A line chart over evenly spaced points (days or months). series: [{ key, label, color?, dashed?, area? }].
 * label: { short(point) for the axis, full(point) for the tooltip and table, header for the table's first column }.
 */
export function LineChart({ title, note, points, series, label, format, tick = compact, height = 240, caption }) {
  const box = useRef(null);
  const width = useWidth(box);
  const [active, setActive] = useState(null);
  const shown = series.filter((s) => points.some((p) => p[s.key] != null));
  if (!points.length || !shown.length) return null;
  const { ticks, min, max } = niceScale(points.flatMap((p) => shown.map((s) => Number(p[s.key]) || 0)));
  const left = Math.max(44, ...ticks.map((t) => tick(t).length * 7 + 14));
  const plot = width - left - MARGIN.right;
  const x = (i) => left + (points.length === 1 ? plot / 2 : (plot * i) / (points.length - 1));
  const y = (v) => MARGIN.top + (height - MARGIN.top - MARGIN.bottom) * (1 - (Number(v) - min) / (max - min));
  const every = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plot / 84))));
  const colour = (s) => s.color || SERIES[series.indexOf(s)];
  const path = (s) => points.map((p, i) => (p[s.key] == null ? null : `${x(i)},${y(p[s.key])}`)).filter(Boolean).join(" L");
  const pick = (event) => {
    const rect = box.current.getBoundingClientRect();
    const at = Math.round(((event.clientX - rect.left - left) / plot) * (points.length - 1));
    setActive(Math.min(points.length - 1, Math.max(0, at)));
  };
  const hovered = active == null ? null : points[active];
  const last = points.length - 1;
  return (
    <figure className="chartCard">
      <figcaption><h3>{title}</h3>{note && <p className="muted">{note}</p>}</figcaption>
      <Legend series={shown.map((s) => ({ ...s, color: colour(s) }))} />
      <div className="chartPlot" ref={box} tabIndex={0} aria-label={`${title}: use the left and right arrow keys to read each point`}
        onPointerMove={pick} onPointerLeave={() => setActive(null)} onKeyDown={stepper(active, setActive, points.length)} onBlur={() => setActive(null)}>
        <svg width={width} height={height} role="img" aria-label={`${title}. ${shown.map((s) => `${s.label} ends at ${format(points[last][s.key] ?? 0)}`).join(". ")}.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} className={t === 0 ? "chartBaseline" : "chartGrid"} />
              <text x={left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="chartTick">{tick(t)}</text>
            </g>
          ))}
          {points.map((p, i) => (i % every === 0 || i === last) && (i === last || last - i >= every / 2) ? (
            <text key={i} x={x(i)} y={height - 8} textAnchor={i === 0 && points.length > 1 ? "start" : i === last && points.length > 1 ? "end" : "middle"} className="chartTick">{label.short(p)}</text>
          ) : null)}
          {shown.map((s) => s.area && (
            <path key={`${s.key}-area`} d={`M${x(0)},${y(0)} L${path(s)} L${x(last)},${y(0)} Z`} fill={colour(s)} opacity="0.1" />
          ))}
          {shown.map((s) => (
            <path key={s.key} d={`M${path(s)}`} fill="none" stroke={colour(s)} strokeWidth="2" strokeDasharray={s.dashed ? "5 4" : undefined}
              strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {shown.map((s) => points[last][s.key] != null && !s.dashed && (
            <circle key={`${s.key}-end`} cx={x(last)} cy={y(points[last][s.key])} r="4.5" fill={colour(s)} className="chartDot" />
          ))}
          {hovered && <>
            <line x1={x(active)} x2={x(active)} y1={MARGIN.top} y2={height - MARGIN.bottom} className="chartCrosshair" />
            {shown.map((s) => hovered[s.key] != null && <circle key={s.key} cx={x(active)} cy={y(hovered[s.key])} r="5" fill={colour(s)} className="chartDot" />)}
          </>}
        </svg>
        {hovered && <Tooltip title={label.full(hovered)} docked={width < 480}
          rows={shown.map((s) => ({ label: s.label, color: colour(s), value: hovered[s.key] == null ? "—" : format(hovered[s.key]) }))}
          style={x(active) > width / 2 ? { right: width - x(active) + 12 } : { left: x(active) + 12 }} />}
      </div>
      <ChartTable points={points} series={shown} label={label} format={format} caption={caption} />
    </figure>
  );
}

/**
 * Upright columns, grouped when there is more than one series. Columns grow from zero: up for gains, down for losses.
 */
export function ColumnChart({ title, note, points, series, label, format, tick = compact, height = 240, caption }) {
  const box = useRef(null);
  const width = useWidth(box);
  const [active, setActive] = useState(null);
  const shown = series.filter((s) => points.some((p) => p[s.key] != null));
  if (!points.length || !shown.length) return null;
  const { ticks, min, max } = niceScale(points.flatMap((p) => shown.map((s) => Number(p[s.key]) || 0)));
  const left = Math.max(44, ...ticks.map((t) => tick(t).length * 7 + 14));
  const plot = width - left - MARGIN.right;
  const band = plot / points.length;
  const gap = 2;
  const bar = Math.max(2, Math.min(24, (band * 0.72 - gap * (shown.length - 1)) / shown.length));
  const group = bar * shown.length + gap * (shown.length - 1);
  const y = (v) => MARGIN.top + (height - MARGIN.top - MARGIN.bottom) * (1 - (Number(v) - min) / (max - min));
  const colour = (s) => s.color || SERIES[series.indexOf(s)];
  const every = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plot / 64))));
  const centre = (i) => left + band * (i + 0.5);
  // A column with a 4px rounded end away from the baseline and a square foot on it.
  const column = (x0, value) => {
    const top = y(Math.max(0, value));
    const bottom = y(Math.min(0, value));
    const h = Math.max(0, bottom - top);
    const r = Math.min(4, bar / 2, h);
    if (h === 0) return "";
    return value >= 0
      ? `M${x0},${bottom} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bar - r} Q${x0 + bar},${top} ${x0 + bar},${top + r} V${bottom} Z`
      : `M${x0},${top} V${bottom - r} Q${x0},${bottom} ${x0 + r},${bottom} H${x0 + bar - r} Q${x0 + bar},${bottom} ${x0 + bar},${bottom - r} V${top} Z`;
  };
  const hovered = active == null ? null : points[active];
  return (
    <figure className="chartCard">
      <figcaption><h3>{title}</h3>{note && <p className="muted">{note}</p>}</figcaption>
      <Legend series={shown.map((s) => ({ ...s, color: colour(s) }))} />
      <div className="chartPlot" ref={box} tabIndex={0} aria-label={`${title}: use the left and right arrow keys to read each column`}
        onPointerLeave={() => setActive(null)} onKeyDown={stepper(active, setActive, points.length)} onBlur={() => setActive(null)}>
        <svg width={width} height={height} role="img" aria-label={`${title}; exact figures in the table`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} className={t === 0 ? "chartBaseline" : "chartGrid"} />
              <text x={left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="chartTick">{tick(t)}</text>
            </g>
          ))}
          {points.map((p, i) => (
            <g key={i} onPointerEnter={() => setActive(i)}>
              <rect x={left + band * i} y={MARGIN.top} width={band} height={height - MARGIN.top - MARGIN.bottom}
                className={active === i ? "chartBand active" : "chartBand"} />
              {shown.map((s, k) => p[s.key] != null && (
                <path key={s.key} d={column(centre(i) - group / 2 + k * (bar + gap), Number(p[s.key]))} fill={colour(s)} />
              ))}
              {i % every === 0 && <text x={centre(i)} y={height - 8} textAnchor="middle" className="chartTick">{label.short(p)}</text>}
            </g>
          ))}
        </svg>
        {hovered && <Tooltip title={label.full(hovered)} docked={width < 480}
          rows={shown.map((s) => ({ label: s.label, color: colour(s), value: hovered[s.key] == null ? "—" : format(hovered[s.key]) }))}
          style={centre(active) > width / 2 ? { right: width - centre(active) + band / 2 } : { left: centre(active) + band / 2 }} />}
      </div>
      <ChartTable points={points} series={shown} label={label} format={format} caption={caption} />
    </figure>
  );
}

/** Sideways bars ranking a few things, biggest first, each with its value at the tip. rows: [{ label, value, detail? }]. */
export function BarList({ title, note, rows, format, color = SERIES[0], empty, limit = 8 }) {
  const ranked = [...rows].filter((r) => Number(r.value) > 0).sort((a, b) => Number(b.value) - Number(a.value));
  const top = ranked.slice(0, limit);
  const rest = ranked.slice(limit).reduce((sum, r) => sum + Number(r.value), 0);
  if (rest > 0) top.push({ label: `${ranked.length - limit} others`, value: rest });
  const largest = Math.max(1, ...top.map((r) => Number(r.value)));
  const total = ranked.reduce((sum, r) => sum + Number(r.value), 0);
  return (
    <figure className="chartCard">
      <figcaption><h3>{title}</h3>{note && <p className="muted">{note}</p>}</figcaption>
      {!top.length ? <p className="muted">{empty}</p> : (
        <ol className="barList">
          {top.map((r) => (
            <li key={r.label} title={`${r.label}: ${format(r.value)}${total ? ` (${Math.round((Number(r.value) / total) * 100)}%)` : ""}`}>
              <span className="barListLabel">{r.label}{r.detail && <small className="muted"> · {r.detail}</small>}</span>
              <span className="barListTrack"><i style={{ width: `${(Number(r.value) / largest) * 100}%`, background: color }} /></span>
              <span className="barListValue">{format(r.value)}<small className="muted"> {total ? `${Math.round((Number(r.value) / total) * 100)}%` : ""}</small></span>
            </li>
          ))}
        </ol>
      )}
    </figure>
  );
}
