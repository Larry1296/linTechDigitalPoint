import { profitText, stockText } from "./plainMoney";

// The first thing on the dashboard: every part of the business together. Products, services and M-Pesa commission, what
// the sold items really cost, running costs and the profit or loss, today and since the start; then the money the owner
// should be holding, added up step by step from the cash book with what each part brought into it, and the M-Pesa
// agency's cash and float beside it: the business's stock for the agency, like goods on the shelves, whose profit is
// the commission. Parts the viewer may not see are left out.
// ``part`` shows only "sales" (the table) or "money" (what should be held); without it, both.
export function OwnerSummary({ summary, money, part }) {
  if (!summary) return null;
  const { today, all_time: all, money: held } = summary;
  const showStock = [today.stock_corrections, all.stock_corrections].some(value => Number(value || 0) !== 0);
  const rows = [
    today.products != null && ["Products sold", today.products, all.products, money],
    today.services != null && ["Services (printing, charging…)", today.services, all.services, money],
    today.commission != null && ["M-Pesa commission", today.commission, all.commission, money],
    [today.commission != null ? "Total income" : "Total sales", today.sales, all.sales, money, true],
    all.cost != null && ["− What the sold items cost you", today.cost, all.cost, money],
    all.expenses != null && ["− Running costs (money spent)", today.expenses, all.expenses, money],
    showStock && ["Stock found or missing in counts", today.stock_corrections, all.stock_corrections, value => stockText(value, money)],
    all.profit != null && ["Profit or loss", today.profit, all.profit, value => profitText(value, money), true],
  ].filter(Boolean);
  const signed = (amount) => Number(amount) < 0 ? `− ${money(-Number(amount))}` : `+ ${money(amount)}`;
  const sales = part !== "money", cash = part !== "sales";
  if (!sales && !held) return null;
  return <section className={`ownerSummary${part ? ` ownerSummary-${part}` : ""}`} aria-labelledby={`owner-summary-title${part ? `-${part}` : ""}`}>
    {sales && <><h2 id={`owner-summary-title${part ? `-${part}` : ""}`}>Your business at a glance</h2>
    <p>{today.commission != null ? "Every part of the business together. From the M-Pesa agency the commission is the profit. Its cash and float are your business's stock for the agency, like goods on the shelves: they make the commission, they are not profit themselves." : "Every part of the business together."}</p>
    <div className="trendTable"><table>
      <caption>Sales, costs and profit</caption>
      <thead><tr><th scope="col">What</th><th scope="col">So far, since you started{summary.since ? ` (${summary.since})` : ""}</th><th scope="col">Of it, today</th></tr></thead>
      <tbody>{rows.map(([label, day, ever, show, strong]) => <tr key={label} className={strong ? "ownerSummaryTotal" : undefined}>
        <th scope="row">{label}</th><td>{show(ever)}</td><td>{show(day)}</td></tr>)}</tbody>
    </table></div></>}
    {cash && held && <div className="ownerSummaryMoney">
      {sales ? <h3>Money you should be holding now</h3> : <h2 id="owner-summary-title-money">Money you should be holding now</h2>}
      <p className="ownerSummaryHeld"><strong>{money(held.expected)}</strong></p>
      <p>{held.places.map(place => `${place.label}: ${money(place.expected)}`).join(" · ")}</p>
      {(held.by_part || []).filter(row => Number(row.amount) !== 0).length > 1 && <p className="ownerSummaryParts">
        <b>Whose money it is:</b> {held.by_part.filter(row => Number(row.amount) !== 0).map(row => `${row.label} ${money(row.amount)}`).join(" · ")}</p>}
      <dl>
        {held.parts.filter(part => Number(part.amount) !== 0 || ["starting", "received", "expenses"].includes(part.key)).map(part =>
          <div key={part.key}><dt>{part.label}</dt><dd>{signed(part.amount)}</dd></div>)}
        <div className="ownerSummaryTotal"><dt>You should have</dt><dd>{money(held.expected)}</dd></div>
      </dl>
      {Number(summary.customers_owe) > 0 && <p>Customers still owe you <strong>{money(summary.customers_owe)}</strong> for things already sold. That is part of your sales but not yet in your hands.</p>}
      <p>Count your money under <a href="/admin/money-check">Money check</a> to see if anything is missing.</p>
      {summary.agency && <p className="ownerSummaryAgency"><b>M-Pesa money in operation: {money(summary.agency.total)}</b> (cash {money(summary.agency.cash)} ·
        float {money(summary.agency.float)}). {summary.agency.business_cash != null
          ? `All the money in the one drawer and on the agent line, so every sale adds to it; the ${money(Number(summary.agency.business_cash) + Number(summary.agency.business_line || 0))} from sales above is part of it, not extra. The rest is your business's stock for the agency, like goods on the shelves; the profit it makes is its commission.`
          : "It is your business's stock for the agency, like goods on the shelves: counted on the M-Pesa desk, so it is not in the total above. The profit it makes is its commission."}</p>}
    </div>}
  </section>;
}
