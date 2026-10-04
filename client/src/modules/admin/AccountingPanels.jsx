import { useState } from "react";
import { profitText, stockText } from "./plainMoney";
import { NetWorthPanel } from "./NetWorthPanel";

const colors = { revenue: "#2563eb", expenses: "#d97706", profit: "#16a34a" };
const labels = { revenue: "Sales", expenses: "Running costs", profit: "Profit (below 0 = loss)" };
const KINDS = { INCOME: "Money in from a sale", EXPENSE: "Money spent", PURCHASE: "Paid a supplier", PRINCIPAL: "M-Pesa customer money", OPENING: "Starting balance", LOAN: "Money lent or repaid", INVESTMENT: "Moved to or from an investment" };

export function AccountingChart({ points, fields, title, money, initialStyle = "line" }) {
  const [style, setStyle] = useState(initialStyle);
  const available = fields.filter(field => points.some(row => row[field] != null));
  const values = points.flatMap(row => available.map(field => Number(row[field]) || 0));
  const min = Math.min(0, ...values), max = Math.max(1, ...values);
  const y = value => 170 - (Number(value) - min) / (max - min) * 150;
  const x = index => 45 + (index + 0.5) / Math.max(points.length, 1) * 690;
  return <section className="accountingPanel">
    <div className="heading"><h2>{title}</h2><label>Chart type<select aria-label={`${title} graph style`} value={style} onChange={event => setStyle(event.target.value)}><option value="line">Line</option><option value="area">Area</option><option value="bar">Bar</option></select></label></div>
    {!available.length ? <p>You don't have access to these figures.</p> : <>
      <p className="muted">{points[0]?.date} to {points.at(-1)?.date}</p>
      <div className="accountingChart"><svg viewBox="0 0 780 215" role="img" aria-label={`${title}; exact amounts available in the data table`}>
        <text x="5" y="14">{money(max)}</text><text x="5" y="195">{money(min)}</text>
        <line x1="45" x2="745" y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.25" />
        {available.map((field, seriesIndex) => <g key={field}>
          {style === "area" && <polygon points={`${x(0)},${y(0)} ${points.map((row, i) => `${x(i)},${y(row[field])}`).join(" ")} ${x(points.length - 1)},${y(0)}`} fill={colors[field]} opacity="0.12" />}
          {style !== "bar" && <polyline points={points.map((row, i) => `${x(i)},${y(row[field])}`).join(" ")} fill="none" stroke={colors[field]} strokeWidth="2" />}
          {points.map((row, i) => style === "bar" ? <rect key={row.date} x={x(i) - 690 / points.length / 2 + seriesIndex * 690 / points.length / available.length} y={Math.min(y(0), y(row[field]))} width={Math.max(0.5, 690 / points.length / available.length - 2)} height={Math.max(0.5, Math.abs(y(row[field]) - y(0)))} fill={colors[field]}><title>{row.date} · {labels[field]}: {money(row[field])}</title></rect> : <circle key={row.date} cx={x(i)} cy={y(row[field])} r={points.length > 60 ? 1.5 : 3} fill={colors[field]}><title>{row.date} · {labels[field]}: {money(row[field])}</title></circle>)}
        </g>)}
        <text x="45" y="212">{points[0]?.date}</text><text x="745" y="212" textAnchor="end">{points.at(-1)?.date}</text>
      </svg></div>
      <div className="accountingLegend">{available.map(field => <span key={field}><i style={{ background: colors[field] }} />{labels[field]}</span>)}</div>
      <details><summary>See the numbers</summary><div className="trendTable"><table><thead><tr><th>Date</th>{available.map(field => <th key={field}>{labels[field]}</th>)}</tr></thead><tbody>{points.map(row => <tr key={row.date}><th scope="row">{row.date}</th>{available.map(field => <td key={field}>{money(row[field])}</td>)}</tr>)}</tbody></table></div></details>
    </>}
  </section>;
}

function OutstandingPanel({ title, data, nameField, empty, note, money }) {
  return <section className="accountingPanel"><h2>{title}</h2>{data.restricted ? <p>You don't have access to this.</p> : <>
    <strong className="accountingValue">{money(data.outstanding)}</strong>{Number(data.count) > 0 && <p>On {data.as_of} · {data.count} {nameField === "customer" ? (data.count === 1 ? "sale" : "sales") : (data.count === 1 ? "delivery" : "deliveries")} not fully paid</p>}<p className="muted">{note}</p>
    {!data.rows.length ? <p>{empty}</p> : <div className="trendTable"><table><caption>Biggest amounts (up to 10)</caption><thead><tr><th>{nameField === "customer" ? "Sale" : "Delivery"}</th><th>{nameField === "customer" ? "Customer" : "Supplier"}</th><th>Still owed</th></tr></thead><tbody>{data.rows.map(row => <tr key={row.reference}><th scope="row">{row.reference}</th><td>{row[nameField]}</td><td>{money(row.amount)}</td></tr>)}</tbody></table></div>}
  </>}</section>;
}

export function PeriodComparison({ data, money }) {
  if (!data.comparison) return null;
  const { period_summary: period, comparison } = data;
  return (
    <section className="accountingPanel"><h2>Compared with before</h2><p>These dates next to the same length of time just before ({comparison.start} to {comparison.end}).</p>
      <div className="accountingKpis">{[["revenue", "Sales"], ["expenses", "Running costs"], ["purchases", "Stock bought"], ["profit", "Profit or loss"]].map(([key, label]) => {
        const metric = comparison.metrics[key];
        const show = key === "profit" ? (value) => profitText(value, money) : money;
        const change = Number(metric.change);
        return <article key={key}><span>{label}</span><strong>{show(period[key])}</strong><small>Before: {show(metric.previous)}</small>{metric.change != null && <small>{change > 0 ? `Up ${money(change)}` : change < 0 ? `Down ${money(-change)}` : "No change"}{metric.percent != null && change ? ` (${Math.abs(Number(metric.percent)).toFixed(0)}%)` : ""}</small>}</article>;
      })}</div>
      {period.profit_margin != null && <p>Out of every {money(100)} of sales, you kept <b>{money(Math.max(0, Number(period.profit_margin)))}</b> as profit{Number(period.profit_margin) < 0 ? " (you made a loss)" : ""}.</p>}
      {Number(period.stock_corrections || 0) !== 0 && <p>Stock found or missing when counting: <b>{stockText(period.stock_corrections, money)}</b>. It is not a running cost, but it does change profit.</p>}
    </section>
  );
}

export function AccountingPanels({ data, money }) {
  if (!data.performance) return null;
  const { period_summary: period, receivables, payables, collections } = data;
  const unitName = (key) => data.business_units?.find(unit => unit.key === key)?.name || key;
  return <>
    <div className="accountingGrid">
      <AccountingChart title={data.performance.granularity === "day" ? "Sales each day" : "Sales each month"} points={data.performance.points} fields={["revenue"]} money={money} initialStyle="area" />
      <AccountingChart title="Sales, running costs and profit" points={data.performance.points} fields={["revenue", "expenses", "profit"]} money={money} />
      <OutstandingPanel title="Customers owe you" data={receivables} nameField="customer" money={money} empty="Every sale has been paid for." note="Sales not yet fully paid, after any returns and price corrections. Online orders that were never paid are not counted." />
      <OutstandingPanel title="You owe suppliers" data={payables} nameField="supplier" money={money} empty="You don't owe any supplier for stock received." note="Stock received from suppliers that you haven't finished paying for. Stock you already had is not included." />
    </div>
    <section className="accountingPanel"><h2>Have customers paid for these sales?</h2>{collections.restricted ? <p>You don't have access to this.</p> : <>
      <p>Sales made from {period.start} to {period.end}, after returns and price corrections, and how much of them has been paid.</p>
      <div className="accountingKpis"><article><span>Sold</span><strong>{money(collections.period_billed)}</strong></article><article><span>Paid</span><strong>{money(collections.collected_on_period_sales)}</strong></article><article><span>Still owed</span><strong>{money(collections.period_outstanding)}</strong></article><article><span>Share paid</span><strong>{collections.rate == null ? "—" : `${Number(collections.rate).toFixed(0)}%`}</strong></article></div>
      {collections.rate != null && <progress aria-label="Share of sales paid" max="100" value={Number(collections.rate)} />}
      <p>{Number(collections.period_outstanding) > 0 ? `Customers still owe ${money(collections.period_outstanding)} for sales made in these dates.` : Number(collections.period_billed) > 0 ? "Everything sold in these dates has been paid for." : "No sales in these dates."}</p>
    </>}</section>
    <section className="accountingPanel"><h2>In short</h2><ul>
      {period.profit != null && <li>You made a <b>{profitText(period.profit, money)}</b>, after {money(period.cogs)} for the items you sold and {money(period.expenses)} in running costs.</li>}
      {!data.inventory.restricted && <li>{data.inventory.low_stock} product(s) are running low and may need restocking.</li>}
      {!payables.restricted && Number(payables.outstanding) > 0 && <li>You still owe suppliers {money(payables.outstanding)} for stock received.</li>}
      {!receivables.restricted && Number(receivables.outstanding) > 0 && <li>Customers still owe you {money(receivables.outstanding)}.</li>}
    </ul></section>
    <section className="accountingPanel"><h2>Best sellers</h2><p>Up to 10 items sold most often in these dates, after returns and price corrections.</p>{!data.top_items.length ? <p>Nothing sold in these dates.</p> : <div className="trendTable"><table><thead><tr><th>Item</th><th>Code</th><th>Number sold</th><th>Sales</th></tr></thead><tbody>{data.top_items.map(row => <tr key={row.id}><th scope="row">{row.name}</th><td>{row.sku}</td><td>{Number(row.quantity).toLocaleString()}</td><td>{money(row.sales)}</td></tr>)}</tbody></table></div>}</section>
    {data.net_worth && <NetWorthPanel worth={data.net_worth} money={money} />}
    {data.recent_entries && <section className="accountingPanel"><h2>Latest money in and out</h2><p>The last 15 in these dates. A minus sign means money went out.</p>{!data.recent_entries.length ? <p>Nothing in these dates.</p> : <div className="trendTable"><table><thead><tr><th>When</th><th>What</th><th>Type</th><th>Part of the business</th><th>Amount</th></tr></thead><tbody>{data.recent_entries.map(row => <tr key={row.id}><td>{new Date(row.occurred_at).toLocaleString(undefined, { timeZone: data.organization.timezone })}</td><th scope="row">{row.reference}</th><td>{KINDS[row.kind] || row.kind}</td><td>{unitName(row.business_unit)}</td><td>{money(row.amount)}</td></tr>)}</tbody></table></div>}</section>}
  </>;
}
