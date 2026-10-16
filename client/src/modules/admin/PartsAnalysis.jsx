import { BarList, ColumnChart, LineChart, SERIES } from "../../components/charts/Charts";

// The usual names of the parts, when the data does not carry the owner's own; same order and colours everywhere here.
const NAMES = { SHOP: "Shop", CYBER: "Cyber", MPESA: "M-Pesa" };
// The whole business, drawn over the parts' lines: dashed and neutral, so it never reads as a fourth part.
const WHOLE = { label: "Whole business", color: "var(--text)", dashed: true };
// The first series colours belong to the parts here, so income, costs and profit take others.
const MEASURES = [{ key: "income", label: "Income", color: "var(--series-4)" }, { key: "costs", label: "Costs", color: "var(--series-5)" },
  { key: "profit", label: "Profit or loss", color: "var(--text)" }];
const asDate = (value) => new Date(`${String(value).length === 7 ? `${value}-15` : value}T12:00:00`);
const monthLabel = { header: "Month", short: (p) => asDate(p.month).toLocaleDateString(undefined, { month: "short" }),
  full: (p) => asDate(p.month).toLocaleDateString(undefined, { month: "long", year: "numeric" }) };
const dayLabel = { header: "Date", short: (p) => asDate(p.date).toLocaleDateString(undefined, { day: "numeric", month: "short" }),
  full: (p) => asDate(p.date).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) };
const percent = (part, whole) => (whole ? Math.round((part / whole) * 100) : 0);

// What the numbers say, in plain sentences: which part made the most, each part's share, and how the latest month
// compares with the one before.
export function partsStory(parts, trend, money, names = NAMES) {
  const lines = [];
  const withProfit = parts.filter((part) => part.profit != null);
  if (withProfit.length > 1) {
    const ranked = [...withProfit].sort((a, b) => b.profit - a.profit);
    const earned = withProfit.filter((part) => part.profit > 0).reduce((sum, part) => sum + part.profit, 0);
    const best = ranked[0];
    if (best.profit > 0) lines.push(`${names[best.key]} made the most profit: ${money(best.profit)}, ${percent(best.profit, earned)}% of what the profitable parts earned.`);
    for (const part of ranked.filter((part) => part.profit < 0)) lines.push(`${names[part.key]} made a loss of ${money(-part.profit)}: its costs were more than it brought in.`);
  }
  const [previous, latest] = trend.slice(-2);
  if (previous && latest) {
    for (const key of Object.keys(names)) {
      const now = latest[`${key}_profit`], before = previous[`${key}_profit`];
      if (now == null || before == null || (!Number(now) && !Number(before))) continue;
      const change = Number(now) - Number(before);
      if (Math.abs(change) < 1) continue;
      lines.push(`${names[key]}'s profit this month is ${money(Math.abs(change))} ${change > 0 ? "more" : "less"} than last month (${money(before)} → ${money(now)}).`);
    }
  }
  return lines;
}

// "How each part of the business is doing": the shop, cyber and M-Pesa agency side by side, so the owner sees which
// part carries the business and what each contributes to the whole business's profit. Shown only when the owner runs
// the business as several parts. M-Pesa counts by its commission and its running costs; its cash and float are the
// agency's working money and are never part of these figures. Costs shared between the parts count by each part's share.
export function PartsAnalysis({ data, money }) {
  if (data.has_parts === false) return null;
  const parts = (data.unit_period || []).map((unit) => ({ key: unit.key, name: unit.name || NAMES[unit.key],
    income: Number(unit.revenue) || 0, costs: unit.profit == null ? null : Number(unit.cogs) + Number(unit.expenses) + Number(unit.stock_corrections || 0),
    profit: unit.profit == null ? null : Number(unit.profit) }));
  if (parts.length < 2) return null;
  const keys = parts.map((part) => part.key);
  const names = Object.fromEntries(parts.map((part) => [part.key, part.name]));
  const colour = (key) => SERIES[keys.indexOf(key) % SERIES.length];
  const series = (field, whole = true) => [...keys.map((key) => ({ key: `${key}_${field}`, label: names[key], color: colour(key) })),
    ...(whole ? [{ key: `TOTAL_${field}`, ...WHOLE }] : [])];
  const trend = data.unit_trend || [];
  const days = data.unit_days || [];
  const profitShown = parts.every((part) => part.profit != null);
  const totalIncome = parts.reduce((sum, part) => sum + part.income, 0);
  const story = partsStory(parts, trend, money, names);
  const whole = { income: totalIncome, costs: parts.reduce((sum, part) => sum + (part.costs || 0), 0), profit: parts.reduce((sum, part) => sum + (part.profit || 0), 0) };
  const period = `${data.period_summary.start} to ${data.period_summary.end}`;
  const partLabel = { header: "Part of the business", short: (p) => p.name, full: (p) => p.name };
  return (
    <section className="businessAnalysis partsAnalysis" aria-labelledby="parts-analysis-title">
      <h2 id="parts-analysis-title">How each part of the business is doing</h2>
      <p className="muted">For {period}. {keys.includes("MPESA") ? "M-Pesa counts by the commission it earns for you, less its running costs; its cash and float are the agency's working money and are not in these figures." : ""}</p>
      {story.length > 0 && <ul className="partsStory">{story.map((line) => <li key={line}>{line}</li>)}</ul>}
      <div className="trendTable partsContribution"><table>
        <caption>What each part contributed to the whole business</caption>
        <thead><tr><th scope="col">Part</th><th scope="col">Brought in</th><th scope="col">Share of the income</th>
          {profitShown && <><th scope="col">Its costs</th><th scope="col">Added to profit</th></>}</tr></thead>
        <tbody>{parts.map((part) => <tr key={part.key}>
          <th scope="row"><span className="partName"><span className="seriesSwatch" style={{ background: colour(part.key) }} aria-hidden="true" />{part.name}</span></th>
          <td>{money(part.income)}</td><td>{percent(part.income, totalIncome)}%</td>
          {profitShown && <><td>{money(part.costs)}</td><td className={part.profit < 0 ? "loss" : undefined}>{part.profit < 0 ? `−${money(-part.profit)}` : money(part.profit)}</td></>}
        </tr>)}</tbody>
        <tfoot><tr><th scope="row">Whole business</th><td>{money(whole.income)}</td><td>100%</td>
          {profitShown && <><td>{money(whole.costs)}</td><td className={whole.profit < 0 ? "loss" : undefined}>{whole.profit < 0 ? `−${money(-whole.profit)}` : money(whole.profit)}</td></>}</tr></tfoot>
      </table>
      {profitShown && <p className="muted">Profit is the whole business's: what all the parts brought in, less all the costs. A cost shared between the
        parts, such as rent, counts against each part by its share, so the parts add up to the whole.</p>}</div>
      <div className="chartGrid2">
        {profitShown && <ColumnChart title="Income, costs and profit of each part" points={parts} label={partLabel} format={money}
          note="What each part brought in, what it cost (goods sold and running costs) and what was left. Below zero is a loss."
          series={MEASURES} />}
        {profitShown
          ? <BarList title="Share of the profit" note="Each part's profit for these dates; a part making a loss is left out of the shares."
            rows={parts.filter((part) => part.profit > 0).map((part) => ({ label: part.name, value: part.profit,
              detail: `${percent(part.profit, parts.filter((p) => p.profit > 0).reduce((sum, p) => sum + p.profit, 0))}% of the profit` }))}
            format={money} empty="No part made a profit in these dates." />
          : <BarList title="Share of the income" note="What each part brought in for these dates." format={money} empty="No income in these dates."
            rows={parts.map((part) => ({ label: part.name, value: part.income, detail: `${percent(part.income, totalIncome)}% of the income` }))} />}
        {days.length > 1 && <LineChart title={profitShown ? "Profit each day, part by part" : "Income each day, part by part"} points={days} label={dayLabel}
          format={money} note="One line for each part, and the dashed line for the whole business: see which part carries it on each day."
          series={series(profitShown ? "profit" : "sales")} />}
        {days.length > 1 && profitShown && <LineChart title="Income each day, part by part" points={days} label={dayLabel} format={money}
          series={series("sales")} />}
      </div>
      {trend.length > 0 && <div className="chartGrid2 analysisMonths">
        {profitShown && <LineChart title="Profit each month, part by part" points={trend} label={monthLabel} format={money}
          note="The last twelve months. A line going up is a part doing better; below zero is a month that part made a loss. The dashed line is the whole business."
          series={series("profit")} />}
        <LineChart title="Income each month, part by part" points={trend} label={monthLabel} format={money}
          note={`What each part brought in${keys.includes("MPESA") ? `: commission for ${names.MPESA}` : ""}. The dashed line is the whole business.`} series={series("sales")} />
        {profitShown && <LineChart title="Running costs each month, part by part" points={trend} label={monthLabel} format={money}
          note="Expenses such as rent, wages and electricity. A cost shared between the parts counts by each part's share. The dashed line is the whole business."
          series={series("costs")} />}
      </div>}
    </section>
  );
}
