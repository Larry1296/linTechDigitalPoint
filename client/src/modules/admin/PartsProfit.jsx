import { profitText } from "./plainMoney";

const SOLD = { SHOP: "Sales", CYBER: "Services", MPESA: "Commission paid" };
const PAGES = { SHOP: "/admin/sales-history", CYBER: "/admin/cyber", MPESA: "/admin/mpesa" };

// The one thing the dashboard brings together: each part's profit or loss since the start, added up. Each part keeps
// its own money, sales and costs on its own page; the agency's profit is its commission, counted once Safaricom pays
// it. Spending (running costs) lowers the profit of the part it was for, a shared cost by each part's share.
export function PartsProfit({ units, total, interest, money }) {
  const parts = units.filter(unit => !unit.restricted && unit.all_time?.profit != null);
  if (!parts.length || total == null) return null;
  return <section className="ownerSummary partsProfit" aria-labelledby="parts-profit-title">
    <h2 id="parts-profit-title">Profit from every part together</h2>
    <p>Each part keeps its own money on its own page. Only the profit each one made is added up here. Money spent lowers it.</p>
    <div className="trendTable"><table>
      <caption>Since you started</caption>
      <thead><tr><th scope="col">Part</th><th scope="col">Brought in</th><th scope="col">Items cost</th><th scope="col">Running costs</th><th scope="col">Profit or loss</th></tr></thead>
      <tbody>{parts.map(unit => <tr key={unit.key} className={Number(unit.all_time.profit) < 0 ? "loss" : undefined}>
        <th scope="row">{PAGES[unit.key] ? <a href={PAGES[unit.key]}>{unit.name}</a> : unit.name}</th>
        <td>{money(unit.all_time.revenue)} <small className="muted">{SOLD[unit.key] || "Sales"}</small></td>
        <td>{Number(unit.all_time.cogs) ? money(unit.all_time.cogs) : "—"}</td>
        <td>{money(unit.all_time.expenses)}</td>
        <td>{profitText(unit.all_time.profit, money)}</td>
      </tr>)}
      {Number(interest || 0) !== 0 && <tr className={Number(interest) < 0 ? "loss" : undefined}>
        <th scope="row"><a href="/admin/investments">Interest on investments</a></th>
        <td colSpan="3"><small className="muted">From the statements, after fees. The money you put in stays yours and out of the books.</small></td>
        <td>{profitText(interest, money)}</td>
      </tr>}</tbody>
      <tfoot><tr className="ownerSummaryTotal"><th scope="row" colSpan="4">Profit from every part together</th><td>{profitText(total, money)}</td></tr></tfoot>
    </table></div>
  </section>;
}
