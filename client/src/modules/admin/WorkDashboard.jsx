import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { StockQuickSearch } from "./StockQuickSearch";

// Where each work page starts, and what it is called on the dashboard.
const START = {
  sales: ["/admin/pos", "Record a sale"],
  products: ["/admin/products", "Products and stock"],
  services: ["/admin/cyber", "Service desk"],
  rooms: ["/admin/rooms", "Front desk"],
  mpesa: ["/admin/mpesa", "M-Pesa agent desk"],
  investments: ["/admin/investments", "Investments"],
};
const plural = (count, one, many = `${one}s`) => `${Number(count).toLocaleString()} ${count === 1 ? one : many}`;

// An employee's dashboard: the work pages the owner gave them and what needs doing on them today. The business's
// money (takings, profit, buying prices, cash, float, commission) is the owner's, so none of it is here.
export function WorkDashboard() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api("/api/v1/inventory/dashboard/work/").then((result) => { setData(result); setError(""); })
    .catch((err) => setError(err.message)), []);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load, { pollMs: 30000 });
  if (!data) return error ? <ErrorState message={error} retry={load} /> : <Loading />;
  const cards = [
    data.sales && ["Your sales today", plural(data.sales.mine_today, "sale"), "Recorded by you", "/admin/sales-history"],
    data.mpesa && ["M-Pesa shift", data.mpesa.shift_open ? "Open" : "Not open", data.mpesa.shift_open ? `${plural(data.mpesa.transactions, "transaction")} recorded by you` : "The business owner opens it", "/admin/mpesa"],
    data.services && ["Service jobs", plural(data.services.waiting, "job") + " waiting", `${plural(data.services.ready, "job")} ready to hand over`, "/admin/cyber"],
    data.rooms && ["Guests", plural(data.rooms.in_house, "guest") + " staying", `${data.rooms.arriving} arriving · ${data.rooms.leaving} leaving today`, "/admin/rooms"],
    data.low_stock && ["Products running low", plural(data.low_stock.count, "product"), data.low_stock.count ? "Tell the business owner" : "Nothing low", null, data.low_stock.count ? "warn" : null],
  ].filter(Boolean);
  return <div className="businessDashboard workDashboard">
    <header className="dashHeader">
      <div className="dashHeaderTitle">
        <span className="eyebrow">{data.business} · Your work</span>
        <h1>Hello, {user?.first_name || data.name}</h1>
        <p>{user?.branch?.name || ""}</p>
      </div>
      {data.pages.length > 0 && <nav className="dashActions" aria-label="Your pages">
        {data.pages.map((page, index) => START[page.key] && <Link key={page.key} to={START[page.key][0]} className={index === 0 ? "main" : undefined}>{START[page.key][1]}</Link>)}
      </nav>}
    </header>
    {!data.pages.length && <p className="formNotice" role="status">The business owner has not given you any pages yet. Ask them to tick the pages you work on.</p>}
    {data.low_stock && <StockQuickSearch />}
    {cards.length > 0 && <section className="dashKpis" aria-label="Your work today">
      {cards.map(([label, value, detail, href, tone]) => {
        const body = <><span>{label}</span><strong>{value}</strong><small>{detail}</small></>;
        return href ? <Link key={label} to={href} className={`dashKpi${tone ? ` ${tone}` : ""}`}>{body}</Link>
          : <article key={label} className={`dashKpi${tone ? ` ${tone}` : ""}`}>{body}</article>;
      })}
    </section>}
    {data.low_stock?.items.length > 0 && <section aria-labelledby="low-stock-title">
      <h2 id="low-stock-title">Running low</h2>
      <div className="tableWrap"><table>
        <thead><tr><th>Product</th><th>Left</th><th>Keep at least</th></tr></thead>
        <tbody>{data.low_stock.items.map((item) => <tr key={item.name}><td>{item.name}</td><td>{Number(item.available).toLocaleString()}</td><td>{Number(item.minimum).toLocaleString()}</td></tr>)}</tbody>
      </table></div>
    </section>}
  </div>;
}
