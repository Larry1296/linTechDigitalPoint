import { useState } from "react";

const when = (value) => (value ? new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const day = (value) => new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

// Each part's share as a bar: what the business owns in blue, what it owes in orange, every bar labelled with its amount.
function WhereItIs({ groups, money }) {
  const rows = groups.filter((g) => Number(g.amount) > 0).sort((a, b) => (a.side === b.side ? Number(b.amount) - Number(a.amount) : a.side === "OWNS" ? -1 : 1));
  const largest = Math.max(1, ...rows.map((g) => Number(g.amount)));
  if (!rows.length) return <p className="muted">Nothing recorded yet.</p>;
  return (
    <ul className="netWorthBars" aria-label="What the business owns and owes, by part">
      {rows.map((g) => (
        <li key={g.key} className={g.side === "OWES" ? "owes" : "owns"} title={`${g.label}: ${money(g.amount)}`}>
          <span className="netWorthBarLabel">{g.side === "OWES" ? "Owes · " : ""}{g.label}</span>
          <span className="netWorthBarTrack"><i style={{ width: `${Math.max(1.5, (Number(g.amount) / largest) * 100)}%` }} /></span>
          <strong>{g.side === "OWES" ? "− " : ""}{money(g.amount)}</strong>
        </li>
      ))}
    </ul>
  );
}

// Net worth over the days it has been kept; one series, so no legend: the heading names it.
function Trend({ history, money }) {
  const [hover, setHover] = useState(null);
  if (history.length < 2) return <p className="muted">The net worth is kept once a day; the trend appears from tomorrow.</p>;
  const values = history.map((h) => Number(h.net_worth));
  const min = Math.min(0, ...values), max = Math.max(1, ...values);
  const x = (i) => 8 + (i / (history.length - 1)) * 584;
  const y = (v) => 150 - ((v - min) / (max - min || 1)) * 132;
  const point = hover == null ? null : history[hover];
  return (
    <div className="netWorthTrend">
      <svg viewBox="0 0 600 170" role="img" aria-label={`Net worth from ${day(history[0].date)} to ${day(history.at(-1).date)}; exact figures in the table below`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const index = Math.round((((event.clientX - box.left) / box.width) * 600 - 8) / 584 * (history.length - 1));
          setHover(Math.max(0, Math.min(history.length - 1, index)));
        }}>
        <line x1="8" x2="592" y1={y(0)} y2={y(0)} className="netWorthAxis" />
        <polyline points={history.map((h, i) => `${x(i)},${y(Number(h.net_worth))}`).join(" ")} className="netWorthLine" />
        {point && <>
          <line x1={x(hover)} x2={x(hover)} y1="10" y2="152" className="netWorthAxis" />
          <circle cx={x(hover)} cy={y(Number(point.net_worth))} r="5" className="netWorthDot" />
        </>}
      </svg>
      <div className="chartDates"><span>{day(history[0].date)}</span><span>{day(history.at(-1).date)}</span></div>
      <p className="netWorthTip" aria-live="polite">{point ? `${day(point.date)}: ${money(point.net_worth)} (owns ${money(point.owns)}, owes ${money(point.owes)})` : "Point at the line to see a day."}</p>
    </div>
  );
}

function placeNote(item, money) {
  if (item.state === "OPEN") return `Shift open since ${when(item.since)} · opened with cash ${money(item.opening_cash)} and float ${money(item.opening_float)} · now cash ${money(item.cash)}, float ${money(item.float)}`;
  if (item.state === "CLOSED") return `No shift open · counted at the last close (${when(item.since)}): cash ${money(item.cash)}, float ${money(item.float)}`;
  if (item.estimated_interest != null && Number(item.estimated_interest)) return `Recorded value · about ${money(item.estimated_interest)} interest since the last statement, not counted until confirmed`;
  if (item.counted != null) {
    const gap = Number(item.difference);
    return `Last counted ${money(item.counted)} on ${when(item.counted_at)}${gap ? ` (${gap > 0 ? "more" : "less"} than expected by ${money(Math.abs(gap))})` : " (matched)"}`;
  }
  return item.method ? "Not counted yet" : "";
}

const LINKS = { money: ["/admin/money-check", "Count or correct"], agency: ["/admin/mpesa", "Agent desk"], investments: ["/admin/investments", "Investments"] };

export function NetWorthPanel({ worth, money }) {
  const places = worth.groups.filter((g) => LINKS[g.key]).flatMap((g) => g.items.map((item) => ({ ...item, group: g.key })));
  return (
    <section className="accountingPanel netWorth" aria-labelledby="net-worth-title">
      <div className="netWorthHead">
        <div>
          <h2 id="net-worth-title">What the business is worth</h2>
          <p className="muted">Everything it owns less everything it owes, as of {when(worth.as_of)}.</p>
        </div>
        <div className="netWorthHero">
          <strong className={Number(worth.net_worth) < 0 ? "negative" : undefined}>{money(worth.net_worth)}</strong>
          <span>Owns {money(worth.owns)} · owes {money(worth.owes)}</span>
        </div>
      </div>
      {worth.left_out.length > 0 && <p className="formNotice formNoticeInfo">Not included because your account cannot see it: {worth.left_out.join(", ")}.</p>}
      <div className="netWorthGrid">
        <div><h3>Where it is</h3><WhereItIs groups={worth.groups} money={money} /></div>
        <div><h3>Net worth over time</h3><Trend history={worth.history} money={money} /></div>
      </div>
      <h3>Money in each place</h3>
      <p className="muted">Shop money is what the app expects from everything recorded; count it to check. M-Pesa agency money is the live shift: what it opened with plus everything since.</p>
      {places.length ? <div className="trendTable"><table>
        <thead><tr><th scope="col">Where</th><th scope="col">Now</th><th scope="col">How it is known</th><th scope="col"><span className="visuallyHidden">Action</span></th></tr></thead>
        <tbody>{places.map((item) => (
          <tr key={item.key}>
            <th scope="row">{item.label}{item.group === "agency" && <small> · M-Pesa agency{item.business_cash != null && `, one drawer with the shop: ${money(Number(item.business_cash) + Number(item.business_line || 0))} of it is from sales`}</small>}</th>
            <td className={Number(item.amount) < 0 ? "negative" : undefined}>{money(item.amount)}</td>
            <td>{placeNote(item, money)}{Number(item.amount) < 0 && item.method && " · below zero: money paid out of here was recorded without the money that came in"}</td>
            <td>{item.method || item.group !== "money" ? <a href={LINKS[item.group][0]}>{LINKS[item.group][1]}</a> : null}</td>
          </tr>))}</tbody>
      </table></div> : <p className="muted">Nothing recorded yet.</p>}
      <details><summary>See the numbers</summary><div className="trendTable"><table>
        <thead><tr><th scope="col">Part</th><th scope="col">Owns</th><th scope="col">Owes</th></tr></thead>
        <tbody>{worth.groups.map((g) => <tr key={g.key}><th scope="row">{g.label}</th><td>{g.side === "OWNS" ? money(g.amount) : "—"}</td><td>{g.side === "OWES" ? money(g.amount) : "—"}</td></tr>)}</tbody>
        <tfoot><tr><th scope="row">Net worth</th><td colSpan="2">{money(worth.net_worth)}</td></tr></tfoot>
      </table></div>
      {worth.history.length > 1 && <div className="trendTable"><table><caption>Net worth each day kept</caption>
        <thead><tr><th scope="col">Day</th><th scope="col">Owns</th><th scope="col">Owes</th><th scope="col">Net worth</th></tr></thead>
        <tbody>{worth.history.map((h) => <tr key={h.date}><th scope="row">{day(h.date)}</th><td>{money(h.owns)}</td><td>{money(h.owes)}</td><td>{money(h.net_worth)}</td></tr>)}</tbody>
      </table></div>}
      </details>
    </section>
  );
}
