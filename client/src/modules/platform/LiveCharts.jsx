import { useEffect, useRef, useState } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { usePrefersReducedMotion } from "../../components/PhotoCarousel";
import "./liveCharts.css";

// The homepage's sample charts behave like a live business: new figures arrive every few seconds
// while a chart is on screen. They hold still off screen, in a hidden tab, or with reduced motion.
export function useLiveTick(interval) {
  const node = useRef(null);
  const [tick, setTick] = useState(0);
  const reduced = usePrefersReducedMotion();
  useEffect(() => {
    const element = node.current;
    if (!element || reduced || typeof IntersectionObserver === "undefined") return undefined;
    let visible = false;
    let timer;
    const schedule = () => {
      window.clearInterval(timer);
      timer = visible && !document.hidden ? window.setInterval(() => setTick((value) => value + 1), interval) : undefined;
    };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; schedule(); });
    observer.observe(element);
    document.addEventListener("visibilitychange", schedule);
    return () => { observer.disconnect(); window.clearInterval(timer); document.removeEventListener("visibilitychange", schedule); };
  }, [interval, reduced]);
  return [node, tick];
}

// Glides a list of numbers to new values over `duration` ms, so SVG shapes morph instead of jumping.
function useTween(target, duration = 900) {
  const [shown, setShown] = useState(target);
  const from = useRef(target);
  const reduced = usePrefersReducedMotion();
  useEffect(() => {
    if (reduced || typeof requestAnimationFrame === "undefined") { from.current = target; setShown(target); return undefined; }
    const start = from.current;
    const began = performance.now();
    let frame;
    const step = (now) => {
      const progress = Math.min(1, (now - began) / duration);
      const eased = 1 - (1 - progress) ** 3;
      const next = target.map((value, index) => (start[index] ?? value) + (value - (start[index] ?? value)) * eased);
      from.current = next;
      setShown(next);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, duration, reduced]);
  return shown;
}

export const between = (low, high) => low + Math.random() * (high - low);
export const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const k = (value) => `${Math.round(value)}k`;
const walk = (values, low, high, drift = 0) => [...values.slice(1), clamp(values.at(-1) + between(-9, 10) + drift, low, high)];
const series = (length, start, low, high) => {
  const values = [start];
  while (values.length < length) values.push(clamp(values.at(-1) + between(-8, 9), low, high));
  return values;
};

// A line (or area) over a rolling window, with a hover crosshair that reads out the nearest point.
function TrendChart({ values, max, area = false, label, unit = "k", pointLabel }) {
  const shown = useTween(values);
  const [hover, setHover] = useState(null);
  const width = 560, height = 170, left = 34, bottom = 22, top = 14;
  const x = (index) => left + (index / (shown.length - 1)) * (width - left - 8);
  const y = (value) => top + (1 - value / max) * (height - top - bottom);
  const line = shown.map((value, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
  const last = shown.length - 1;
  const point = hover ?? last;
  const ticks = [0, max / 2, max];
  return (
    <svg className={`liveTrend${area ? " area" : ""}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}
      onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        const ratio = ((event.clientX - box.left) / box.width * width - left) / (width - left - 8);
        setHover(clamp(Math.round(ratio * last), 0, last));
      }}
      onPointerLeave={() => setHover(null)}>
      {ticks.map((tick) => <g key={tick}><line className="liveGrid" x1={left} x2={width - 8} y1={y(tick)} y2={y(tick)} /><text className="liveAxis" x={left - 6} y={y(tick) + 3} textAnchor="end">{Math.round(tick)}</text></g>)}
      {area && <path className="liveAreaFill" d={`${line} L${x(last)},${y(0)} L${x(0)},${y(0)} Z`} />}
      <path className="liveLine" d={line} />
      <line className="liveCrosshair" x1={x(point)} x2={x(point)} y1={top} y2={y(0)} opacity={hover == null ? 0 : 1} />
      <circle className="liveDot" cx={x(point)} cy={y(shown[point])} r="5" />
      <text className="liveValue" x={clamp(x(point), left + 40, width - 50)} y={Math.max(y(shown[point]) - 12, 12)} textAnchor="middle">
        {pointLabel(point, last)}: {Math.round(shown[point])}{unit}
      </text>
    </svg>
  );
}

// A headline number with its recent trend. `lowerIsBetter` flips which direction reads as good.
function StatTile({ label, value, note, trend, format = k, lowerIsBetter = false }) {
  const shown = useTween([value, ...trend]);
  const [current, ...line] = shown;
  const max = Math.max(...line) * 1.1, min = Math.min(...line) * 0.9;
  const points = line.map((point, index) => `${(index / (line.length - 1)) * 100},${30 - ((point - min) / (max - min || 1)) * 28}`).join(" ");
  const up = trend.at(-1) >= trend.at(-2);
  const good = lowerIsBetter ? !up : up;
  return (
    <article className="liveTile">
      <span>{label}</span>
      <strong>{format(current)}</strong>
      <small className={good ? "good" : "bad"}>{up ? <ArrowUpRight size={14} aria-label="Up" /> : <ArrowDownRight size={14} aria-label="Down" />} {note}</small>
      <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true"><polyline points={points} /></svg>
    </article>
  );
}

const METHODS = [["Cash", "cash"], ["M-Pesa", "mpesa"], ["Bank", "bank"]];
function PaymentsDonut({ shares }) {
  const shown = useTween(shares);
  const total = shown.reduce((sum, value) => sum + value, 0);
  const radius = 54, circumference = 2 * Math.PI * radius, gap = 3;
  const lengths = shown.map((value) => (value / total) * circumference);
  const starts = lengths.map((_, index) => lengths.slice(0, index).reduce((sum, length) => sum + length, 0));
  return (
    <div className="liveDonut">
      <svg viewBox="0 0 140 140" role="img" aria-label={`Sample payments by method: ${METHODS.map(([name], index) => `${name} ${Math.round(shares[index] / shares.reduce((a, b) => a + b, 0) * 100)}%`).join(", ")}`}>
        {lengths.map((length, index) => <circle key={index} className={`liveSlice ${METHODS[index][1]}`} cx="70" cy="70" r={radius}
          strokeDasharray={`${Math.max(length - gap, 0)} ${circumference}`} strokeDashoffset={-starts[index]} />)}
        <text className="liveDonutTotal" x="70" y="68" textAnchor="middle">{k(total)}</text>
        <text className="liveDonutLabel" x="70" y="86" textAnchor="middle">this week</text>
      </svg>
      <ul className="liveLegend">
        {METHODS.map(([name, key], index) => <li key={key}><i className={key} />{name}<b>{Math.round((shown[index] / total) * 100)}%</b></li>)}
      </ul>
    </div>
  );
}

const PRODUCTS = ["Phone chargers", "Earphones", "Phone covers", "USB cables", "Rechargeable bulbs"];
function TopSellers({ units }) {
  const shown = useTween(units);
  const order = PRODUCTS.map((name, index) => ({ name, value: shown[index], index })).sort((a, b) => b.value - a.value);
  const max = Math.max(...shown) * 1.1;
  return (
    <ol className="liveBars" aria-label={`Sample top sellers this week: ${order.map((row) => `${row.name} ${Math.round(row.value)} units`).join(", ")}`}>
      {order.map((row) => (
        <li key={row.name} style={{ order: order.indexOf(row) }} title={`${row.name}: ${Math.round(row.value)} units`}>
          <span>{row.name}</span>
          <div><i style={{ width: `${(row.value / max) * 100}%` }} /></div>
          <b>{Math.round(row.value)}</b>
        </li>
      ))}
    </ol>
  );
}

const DAY_MS = 86400000;
const dayName = (offset) => new Date(Date.now() - offset * DAY_MS).toLocaleDateString(undefined, { day: "numeric", month: "short" });

// "Your business, live": a dashboard of sample charts that keep updating like a real shop's day.
export function LiveDashboard() {
  const [node, tick] = useLiveTick(3000);
  const [data, setData] = useState(() => ({
    revenue: series(30, 48, 28, 92),
    cash: series(30, 60, 35, 95),
    shares: [38, 49, 13],
    units: [46, 38, 31, 27, 19],
    today: [52, 55, 49, 58, 61, 57, 64, 66],
    lowStock: [9, 8, 8, 7, 9, 8, 7, 6],
    owed: [34, 36, 33, 31, 35, 32, 30, 29],
  }));
  useEffect(() => {
    if (!tick) return;
    setData((current) => ({
      revenue: walk(current.revenue, 28, 92, 0.6),
      cash: walk(current.cash, 35, 95, 0.3),
      shares: current.shares.map((share, index) => clamp(share + between(-4, 4) + (index === 1 ? 0.4 : 0), 8, 60)),
      units: current.units.map((value) => clamp(value + between(-5, 6), 8, 70)),
      today: walk(current.today, 30, 90, 1),
      lowStock: [...current.lowStock.slice(1), clamp(Math.round(current.lowStock.at(-1) + between(-2, 2)), 2, 14)],
      owed: walk(current.owed, 15, 50, -0.3),
    }));
  }, [tick]);
  return (
    <section className="saasSection homeLive" aria-labelledby="home-live-title" ref={node}>
      <div className="homeLiveIntro">
        <span className="eyebrow">Analytics, as it happens</span>
        <h2 id="home-live-title">Watch your business move.</h2>
        <p>Every sale, payment and delivery updates your reports straight away. These charts use sample data to show what your dashboard looks like on a busy day.</p>
        <span className="homeSampleLabel"><span className="homeLiveDot" aria-hidden="true" />Sample data · updating live</span>
      </div>
      <div className="liveGridLayout">
        <StatTile label="Sales today" value={data.today.at(-1)} trend={data.today} note="vs. this time yesterday" />
        <StatTile label="Items to restock" value={data.lowStock.at(-1)} trend={data.lowStock} note="below restock level" format={(value) => Math.round(value)} lowerIsBetter />
        <StatTile label="Customers owe you" value={data.owed.at(-1)} trend={data.owed} note="credit sales outstanding" lowerIsBetter />
        <article className="liveCard wide">
          <header><h3>Daily revenue</h3><small>Last 30 days · thousands</small></header>
          <TrendChart values={data.revenue} max={100} label="Sample daily revenue for the last 30 days, in thousands"
            pointLabel={(index, last) => (index === last ? "Today" : dayName(last - index))} />
        </article>
        <article className="liveCard">
          <header><h3>Payments by method</h3><small>This week</small></header>
          <PaymentsDonut shares={data.shares} />
        </article>
        <article className="liveCard wide">
          <header><h3>Cash position</h3><small>Cash, bank and M-Pesa · last 30 days · thousands</small></header>
          <TrendChart area values={data.cash} max={100} label="Sample cash position for the last 30 days, in thousands"
            pointLabel={(index, last) => (index === last ? "Now" : dayName(last - index))} />
        </article>
        <article className="liveCard">
          <header><h3>Top sellers</h3><small>Units sold this week</small></header>
          <TopSellers units={data.units} />
        </article>
      </div>
    </section>
  );
}
