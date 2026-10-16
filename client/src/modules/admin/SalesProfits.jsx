import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { profitText } from "./plainMoney";

const PAGE = 50;

// Every sale ever made, newest first, with what it brought in, what the items cost and the profit it made, as the
// books have it now (after returns and price corrections), and where the sales' profit had reached once it was added
// to every sale before it. Fifty at a time; find one by number, customer or item.
export function SalesProfits({ money, timezone, refreshKey }) {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const wait = setTimeout(() => {
      api(`/api/v1/commerce/sales/?${new URLSearchParams({ page, q: query.trim() })}`)
        .then(result => { if (live) { setData(result); setError(""); } })
        .catch(err => { if (live) setError(err.message); });
    }, query ? 300 : 0);
    return () => { live = false; clearTimeout(wait); };
  }, [page, query, refreshKey]);
  if (data && !data.profit_visible) return null;
  const rows = data?.results || [];
  const pages = Math.max(1, Math.ceil((data?.count || 0) / PAGE));
  const total = (key) => rows.reduce((sum, sale) => sum + Number(sale.figures?.[key] || 0), 0);
  const when = (value) => new Date(value).toLocaleString(undefined, { timeZone: timezone, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const items = (sale) => sale.items.map(item => `${Number(item.quantity)} × ${item.item}`).join(", ");
  return <section className="accountingPanel salesProfits" aria-labelledby="sales-profits-title">
    <h2 id="sales-profits-title">Every sale and its profit</h2>
    <p className="muted">All sales ever made, newest first. Profit is what the sale brought in less what the items cost you, after any return or price correction. "Profit so far" adds each sale's profit to all the sales before it, before running costs.</p>
    <label>Find a sale<input type="search" value={query} placeholder="Sale number, customer or item"
      onChange={event => { setQuery(event.target.value); setPage(1); }} /></label>
    {error && <p className="formNotice formNoticeError" role="alert">Can't load the sales right now: {error}</p>}
    {!data ? <p>Loading sales…</p> : !rows.length ? <p>{query ? "No sale matches that." : "No sales yet."}</p> : <>
      <div className="trendTable"><table>
        <caption>{data.count.toLocaleString()} {data.count === 1 ? "sale" : "sales"}{query ? " found" : " in all"} · page {page} of {pages}</caption>
        <thead><tr><th scope="col">When</th><th scope="col">Sale</th><th scope="col">Customer</th><th scope="col">What was sold</th>
          <th scope="col">Sold for</th><th scope="col">Items cost</th><th scope="col">Profit</th><th scope="col">Profit so far</th></tr></thead>
        <tbody>{rows.map(sale => <tr key={sale.id} className={Number(sale.figures?.profit) < 0 ? "loss" : undefined}>
          <td>{when(sale.created_at)}</td><th scope="row">{sale.number}</th><td>{sale.customer}</td><td>{items(sale)}</td>
          <td>{money(sale.figures?.sales)}</td><td>{money(sale.figures?.cost)}</td><td>{profitText(sale.figures?.profit, money)}</td><td>{profitText(sale.figures?.profit_so_far, money)}</td>
        </tr>)}</tbody>
        <tfoot><tr><th scope="row" colSpan="4">These {rows.length} {rows.length === 1 ? "sale" : "sales"}</th>
          <td>{money(total("sales"))}</td><td>{money(total("cost"))}</td><td>{profitText(total("profit"), money)}</td><td></td></tr></tfoot>
      </table></div>
      {pages > 1 && <div className="actionRow">
        <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer sales</button>
        <button type="button" className="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Older sales</button>
      </div>}
    </>}
  </section>;
}
