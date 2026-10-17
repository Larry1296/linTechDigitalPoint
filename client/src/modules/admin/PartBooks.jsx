import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";
import { ColumnChart, SERIES } from "../../components/charts/Charts";
import { profitText } from "./plainMoney";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const monthLabel = { header: "Month", short: (p) => new Date(`${p.month}-15T12:00:00`).toLocaleDateString(undefined, { month: "short" }),
  full: (p) => new Date(`${p.month}-15T12:00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" }) };
const WORDS = { SHOP: { sold: "Sales", count: "sales" }, CYBER: { sold: "Income from services", count: "services done" },
  MPESA: { sold: "Commission earned", count: "transactions" } };

// One part of the business on its own (server inventory/part_books.py): what it sold, what the items cost, its running
// costs and its profit or loss since the start, month by month, and its money. The dashboard adds the parts together.
export function PartBooks({ part, refreshKey }) {
  const [books, setBooks] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api(`/api/v1/inventory/parts/${part}/`).then((found) => { if (live) { setBooks(found); setError(""); } })
      .catch((err) => { if (live) setError(err.status === 403 ? "" : err.message); });
    return () => { live = false; };
  }, [part, refreshKey]);
  if (error) return <p className="formNotice formNoticeError" role="alert">Could not load {part === "SHOP" ? "the shop's" : part === "CYBER" ? "cyber's" : "the agency's"} own figures: {error}</p>;
  if (!books?.all_time) return null;
  const words = WORDS[part];
  const ever = books.all_time;
  const seen = ever.profit != null;
  const steps = [[words.sold, money(ever.revenue)],
    seen && Number(ever.cogs) !== 0 && ["− What the sold items cost (buying price)", money(ever.cogs)],
    seen && ["− Running costs", money(ever.expenses)],
    seen && Number(ever.stock_corrections) !== 0 && [Number(ever.stock_corrections) < 0 ? "+ Stock found in counts" : "− Stock missing in counts", money(Math.abs(Number(ever.stock_corrections)))],
  ].filter(Boolean);
  const points = books.months.map((p) => ({ ...p, revenue: Number(p.revenue), profit: p.profit == null ? null : Number(p.profit) }));
  return <section className="businessAnalysis partBooks" aria-labelledby={`part-books-${part}`}>
    <h2 id={`part-books-${part}`}>{books.label} on its own</h2>
    <p className="muted">Since {books.since || "the start"}: {Number(books.count).toLocaleString()} {words.count}. Only {books.label}'s own figures; the dashboard adds every part together.</p>
    <dl className="dashList">
      {steps.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      {seen && <div className="ownerSummaryTotal"><dt>Profit or loss</dt><dd className={Number(ever.profit) < 0 ? "negative" : undefined}>{profitText(ever.profit, money)}</dd></div>}
      {books.money && <div><dt>{books.label}'s money now</dt><dd>{money(books.money.amount)}{books.money.of != null && ` of ${money(books.money.of)} the business holds (one drawer)`}</dd></div>}
    </dl>
    {points.length > 0 && <ColumnChart title={`${books.label} month by month`} points={points} label={monthLabel} format={money}
      note={seen ? "Profit or loss is after the items' cost and its running costs." : undefined}
      series={[{ key: "revenue", label: words.sold }, ...(seen ? [{ key: "profit", label: "Profit or loss", color: SERIES[2] }] : [])]} />}
  </section>;
}
