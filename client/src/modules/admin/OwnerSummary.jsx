import { profitText, stockText } from "./plainMoney";

// The first thing on the dashboard: the shop and services without the M-Pesa agency. Sales, what the sold items really
// cost, running costs and the profit or loss, today and since the start; then the money the owner should be holding,
// added up step by step from the cash book. Parts the viewer may not see are left out.
export function OwnerSummary({ summary, money }) {
  if (!summary) return null;
  const { today, all_time: all, money: held } = summary;
  const showStock = [today.stock_corrections, all.stock_corrections].some(value => Number(value || 0) !== 0);
  const rows = [
    today.products != null && ["Products sold", today.products, all.products, money],
    today.services != null && ["Services (printing, charging…)", today.services, all.services, money],
    ["Total sales", today.sales, all.sales, money, true],
    all.cost != null && ["− What the sold items cost you", today.cost, all.cost, money],
    all.expenses != null && ["− Running costs (money spent)", today.expenses, all.expenses, money],
    showStock && ["Stock found or missing in counts", today.stock_corrections, all.stock_corrections, value => stockText(value, money)],
    all.profit != null && ["Profit or loss", today.profit, all.profit, value => profitText(value, money), true],
  ].filter(Boolean);
  const signed = (amount) => Number(amount) < 0 ? `− ${money(-Number(amount))}` : `+ ${money(amount)}`;
  return <section className="ownerSummary" aria-labelledby="owner-summary-title">
    <h2 id="owner-summary-title">Your business at a glance (without M-Pesa)</h2>
    <p>Products and services only. M-Pesa agency cash, float and commission are kept apart and checked on the M-Pesa desk.</p>
    <div className="trendTable"><table>
      <caption>Sales, costs and profit</caption>
      <thead><tr><th scope="col">What</th><th scope="col">Today</th><th scope="col">Since you started{summary.since ? ` (${summary.since})` : ""}</th></tr></thead>
      <tbody>{rows.map(([label, day, ever, show, strong]) => <tr key={label} className={strong ? "ownerSummaryTotal" : undefined}>
        <th scope="row">{label}</th><td>{show(day)}</td><td>{show(ever)}</td></tr>)}</tbody>
    </table></div>
    {held && <div className="ownerSummaryMoney">
      <h3>Money you should be holding now</h3>
      <p className="ownerSummaryHeld"><strong>{money(held.expected)}</strong></p>
      <p>{held.places.map(place => `${place.label}: ${money(place.expected)}`).join(" · ")}</p>
      <dl>
        {held.parts.filter(part => Number(part.amount) !== 0 || ["starting", "received", "expenses"].includes(part.key)).map(part =>
          <div key={part.key}><dt>{part.label}</dt><dd>{signed(part.amount)}</dd></div>)}
        <div className="ownerSummaryTotal"><dt>You should have</dt><dd>{money(held.expected)}</dd></div>
      </dl>
      {Number(summary.customers_owe) > 0 && <p>Customers still owe you <strong>{money(summary.customers_owe)}</strong> for things already sold. That is part of your sales but not yet in your hands.</p>}
      <p>Count your money under <a href="/admin/money-check">Money check</a> to see if anything is missing.</p>
    </div>}
  </section>;
}
