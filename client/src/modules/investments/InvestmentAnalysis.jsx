import { useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { ColumnChart, LineChart, SERIES } from "../../components/charts/Charts";

// The whole picture of the investments, all funds together: what is in them day by day and how much of it is interest,
// the interest earned each month (confirmed by a statement or still an estimate) with the money that earned it, and
// money taken out by how it was paid: standard (to the bank, free) or instant (for a charge that leaves the fund too).
// Worked out from the day-by-day figures and the history the page already has.

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const signed = (value) => (Number(value) < 0 ? `− ${money(-value)}` : money(value));
const percent = (value) => `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
const asDate = (value) => new Date(`${String(value).slice(0, 10)}T12:00:00`);
const dayName = (value) => asDate(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
const monthName = (month, style = "long") => new Date(`${month}-15T12:00:00`).toLocaleDateString(undefined, { month: style, year: "numeric" });
const round = (value) => Math.round(value * 100) / 100;
const dayLabel = { header: "Day", short: (p) => asDate(p.date).toLocaleDateString(undefined, { day: "numeric", month: "short" }), full: (p) => dayName(p.date) };
const monthLabel = { header: "Month", short: (p) => new Date(`${p.month}-15T12:00:00`).toLocaleDateString(undefined, { month: "short" }), full: (p) => monthName(p.month) };

// Money really moved in or out: not undone, and not the old "marked as the business's" pairs that never moved money.
const live = (m) => !m.reversed_at && !m.switch;
const isCharge = (m) => Boolean(m.charge_of);

// Every day, all funds added together, oldest first: {date, value, invested, interest, rate}.
export function combinedDays(investments) {
  const byDate = new Map();
  for (const investment of investments) {
    for (const d of investment.daily || []) {
      const row = byDate.get(d.date) || { date: d.date, value: 0, invested: 0, interest: 0, earning: 0 };
      row.value += Number(d.value);
      row.invested += Number(d.invested);
      row.interest += Number(d.interest);
      row.earning += Number(d.value) * Number(d.rate || 0);  // to weight the rate by the money earning it
      byDate.set(d.date, row);
    }
  }
  return [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1))
    .map((d) => ({ ...d, value: round(d.value), invested: round(d.invested), interest: round(d.interest), rate: d.value ? d.earning / d.value : 0 }));
}

// Month by month, oldest first: the interest earned, what earned it (the average in the funds that month), the rate,
// the money put in and taken out, the instant charges, and whether a statement has confirmed the month's interest.
export function monthly(investments, days) {
  const months = new Map();
  const month = (key) => {
    if (!months.has(key)) months.set(key, { month: key, interest: 0, days: 0, held: 0, rate: 0, putIn: 0, takenOut: 0, charges: 0, confirmed: false, end: 0 });
    return months.get(key);
  };
  for (const d of days) {
    const row = month(d.date.slice(0, 7));
    row.interest += d.interest;
    row.days += 1;
    row.held += d.value;
    row.rate += d.rate;
    row.end = d.value;
  }
  for (const m of investments.flatMap((i) => i.movements || []).filter(live)) {
    const row = months.get(String(m.occurred_on).slice(0, 7));
    if (!row) continue;
    if (m.kind === "DEPOSIT") row.putIn += Number(m.amount);
    else if (m.kind === "WITHDRAWAL" && isCharge(m)) row.charges += Number(m.amount);
    else if (m.kind === "WITHDRAWAL") row.takenOut += Number(m.amount);
    else row.confirmed = true;  // interest or fees from a statement
  }
  return [...months.values()].map((row) => {
    const average = row.days ? row.held / row.days : 0;
    return { ...row, interest: round(row.interest), average: round(average), rate: row.days ? row.rate / row.days : 0,
      // What the interest came to as a yearly rate on the money that earned it, after tax.
      earnedRate: average > 0 && row.days ? (row.interest / average) * (365 / row.days) * 100 : 0 };
  });
}

// Money taken out, by how it was paid.
export function withdrawals(investments) {
  const all = investments.flatMap((i) => i.movements || []).filter(live);
  const out = all.filter((m) => m.kind === "WITHDRAWAL" && !isCharge(m));
  const charges = all.filter((m) => m.kind === "WITHDRAWAL" && isCharge(m));
  const sum = (rows) => round(rows.reduce((total, m) => total + Number(m.amount), 0));
  const instant = out.filter((m) => m.speed === "INSTANT");
  const standard = out.filter((m) => m.speed === "STANDARD");
  const unknown = out.filter((m) => !m.speed);
  const byMonth = new Map();
  for (const m of out) {
    const key = String(m.occurred_on).slice(0, 7);
    const row = byMonth.get(key) || { month: key, instant: 0, standard: 0, unknown: 0 };
    row[m.speed === "INSTANT" ? "instant" : m.speed === "STANDARD" ? "standard" : "unknown"] += Number(m.amount);
    byMonth.set(key, row);
  }
  return { instant: { count: instant.length, amount: sum(instant) }, standard: { count: standard.length, amount: sum(standard) },
    unknown: { count: unknown.length, amount: sum(unknown) }, charges: { count: charges.length, amount: sum(charges) },
    months: [...byMonth.values()].sort((a, b) => (a.month < b.month ? -1 : 1)) };
}

function MonthDays({ days, month }) {
  const rows = days.filter((d) => d.date.startsWith(month)).reverse();
  return (
    <table className="loanRepayments stackTable" aria-label={`Interest each day in ${monthName(month)}`}>
            <thead><tr><th>Date</th><th>In the funds</th><th>Yearly rate</th><th>Interest that day</th></tr></thead>
      <tbody>{rows.map((d) => (
        <tr key={d.date}><td data-label="Date">{dayName(d.date)}</td><td data-label="In the funds">{money(d.value)}</td>
          <td data-label="Yearly rate">{percent(d.rate)}</td><td data-label="Interest that day">{signed(d.interest)}</td></tr>))}</tbody>
    </table>
  );
}

export function InvestmentAnalysis({ investments, earningYear }) {
  const days = combinedDays(investments);
  const months = monthly(investments, days);
  const out = withdrawals(investments);
  const [open, setOpen] = useState(months.length ? months[months.length - 1].month : "");
  if (days.length < 2) return null;
  const now = days[days.length - 1];
  const interest = round(now.value - now.invested);
  const average = days.reduce((sum, d) => sum + d.value, 0) / days.length;
  const returned = average > 0 ? (interest / average) * (365 / days.length) * 100 : 0;
  const best = months.filter((m) => m.days >= 20).reduce((a, b) => (!a || b.interest > a.interest ? b : a), null);
  const thisMonth = months[months.length - 1];
  const points = days.map((d) => ({ date: d.date, value: d.value, invested: d.invested, earned: round(d.value - d.invested) }));
  return (
    <section className="businessAnalysis investAnalysis" aria-labelledby="invest-analysis-title">
      <div className="sectionHeading"><h2 id="invest-analysis-title">Analysis</h2></div>
      <div className="metrics investMetrics">
        <article><span>Interest earned so far</span><strong>{money(interest)}</strong>
          <small>Since {dayName(days[0].date)}, after tax and fees{thisMonth && !thisMonth.confirmed ? `; ${monthName(thisMonth.month)}'s is an estimate` : ""}</small></article>
        <article><span>Your money earned</span><strong>{percent(returned)} a year</strong>
          <small>After tax, on an average of {money(average)} in the funds</small></article>
        {thisMonth && <article><span>Interest this month</span><strong>{money(thisMonth.interest)}</strong>
          <small>{monthName(thisMonth.month)} so far: {thisMonth.confirmed ? "confirmed by the statement" : "an estimate until the statement comes"}</small></article>}
        <article><span>Instant charges</span><strong>{money(out.charges.amount)}</strong>
          <small>{out.charges.count} charge{out.charges.count === 1 ? "" : "s"}, taken out of the fund; standard to the bank is free</small></article>
        {earningYear > 0 && <article><span>In a year from now</span><strong>{money(now.value + earningYear)}</strong>
          <small>If nothing moves: about {money(earningYear)} more interest at today's rate, after tax</small></article>}
      </div>

      <div className="chartGrid2">
        <LineChart title="Your money in the funds, day by day" points={points} label={dayLabel} format={money}
          note="Everything in the funds, interest left in included, next to what was put in less taken out."
          series={[{ key: "value", label: "Total invested", area: true }, { key: "invested", label: "Put in, less taken out", dashed: true, color: SERIES[1] }]} />
        <LineChart title="Interest earned so far, day by day" points={points} label={dayLabel} format={money}
          note="All the interest earned and left in (after tax and fees): it grows every day and is invested with the rest."
          series={[{ key: "earned", label: "Interest earned", color: SERIES[2], area: true }]} />
        <ColumnChart title="Interest earned each month" points={months} label={monthLabel} format={money}
          note={`After tax and fees.${thisMonth && !thisMonth.confirmed ? ` ${monthName(thisMonth.month)} is so far, an estimate until its statement.` : ""}`}
          series={[{ key: "interest", label: "Interest", color: SERIES[2] }]} />
        {out.months.length > 0 && <ColumnChart title="Money taken out each month, by how" points={out.months} label={monthLabel} format={money}
          note="Instant costs a charge each time; standard to the bank is free."
          series={[{ key: "standard", label: "Standard (free)" }, { key: "instant", label: "Instant (charged)", color: SERIES[3] },
            ...(out.unknown.count ? [{ key: "unknown", label: "Not said", color: SERIES[4] }] : [])]} />}
      <div className="chartCard investWithdrawals investWide">
          <h3>Money taken out</h3>
          <ul>
            <li><b>Instant:</b> {out.instant.count} time{out.instant.count === 1 ? "" : "s"}, {money(out.instant.amount)}, plus {money(out.charges.amount)} in charges</li>
            <li><b>Standard (to the bank):</b> {out.standard.count} time{out.standard.count === 1 ? "" : "s"}, {money(out.standard.amount)}, no charges</li>
            {out.unknown.count > 0 && <li><b>Not said:</b> {out.unknown.count} time{out.unknown.count === 1 ? "" : "s"}, {money(out.unknown.amount)} (recorded before the choice)</li>}
          </ul>
          {out.charges.amount > 0 && <p className="muted">Choosing standard when the money can wait a day or two would have saved {money(out.charges.amount)}.</p>}
        </div>
      </div>

      <h3>Interest month by month</h3>
      {best && <p className="muted">The best full month so far was {monthName(best.month)}: {money(best.interest)} on an average of {money(best.average)}.</p>}
      <div className="investTableScroll"><table className="loanRepayments stackTable investMonths" aria-label={`Interest earned each month and the money that earned it`}>
                <thead><tr><th>Month</th><th>Interest</th><th>Earned on (average)</th><th>Yearly rate</th>
          <th>Put in</th><th>Taken out</th><th>Charges</th><th>At month end</th></tr></thead>
        <tbody>{[...months].reverse().map((m) => (
          <tr key={m.month} className={open === m.month ? "investMonthOpen" : undefined}>
            <td data-label="Month"><button type="button" className="linkButton" aria-expanded={open === m.month}
              onClick={() => setOpen(open === m.month ? "" : m.month)}>{monthName(m.month)}</button>
              <small> · {m.confirmed ? "statement" : "estimate"}{m.days < 28 ? `, ${m.days} days` : ""}</small></td>
            <td data-label="Interest"><strong>{signed(m.interest)}</strong></td>
            <td data-label="Earned on (average)">{money(m.average)}</td>
            <td data-label="Yearly rate">{percent(m.rate)}<small> · came to {percent(m.earnedRate)} after tax</small></td>
            <td data-label="Put in">{money(m.putIn)}</td>
            <td data-label="Taken out">{money(m.takenOut)}</td>
            <td data-label="Charges">{money(m.charges)}</td>
            <td data-label="At month end">{money(m.end)}</td>
          </tr>))}</tbody>
      </table></div>
      {open && <>
        <h4>{monthName(open)} day by day</h4>
        <MonthDays days={days} month={open} />
        <p className="muted">Interest is worked out each day on what is in the funds that day. A statement day shows the difference the statement made.</p>
      </>}
    </section>
  );
}
