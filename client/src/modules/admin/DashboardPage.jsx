import { BestSellers, CollectionsPanel, InShort, OwedPanels, PeriodComparison, RecentEntries } from "./AccountingPanels";
import { interestText, owedText, profitSum, profitText, stockText } from "./plainMoney";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useAuth } from "../../core/auth/AuthContext";
import { api } from "../../core/api/client";
import { ErrorState, Loading } from "../../components/States";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { InvestmentReminder } from "../investments/InvestmentReminder";
import { CommissionReminder } from "../mpesa/CommissionReminder";
import { RecordsSummary } from "./RecordsSummary";
import { PartsProfit } from "./PartsProfit";
import { ChamaDashboardCard } from "../chama/ChamaDashboardCard";
import { BusinessAnalysis } from "./BusinessAnalysis";
import { StockQuickSearch } from "./StockQuickSearch";
import { SalesProfits } from "./SalesProfits";

// On phones tables stack row by row; each figure is labelled with its column heading so it still says what it is.
function useColumnLabels(root) {
  useLayoutEffect(() => {
    for (const table of root.current?.querySelectorAll("table") || []) {
      const headings = [...table.querySelectorAll("thead th")].map((cell) => cell.textContent.trim());
      if (!headings.length) continue;
      for (const row of table.querySelectorAll("tbody tr, tfoot tr")) {
        let column = 0;
        for (const cell of row.children) {
          if (!cell.hasAttribute("data-label")) cell.setAttribute("data-label", cell.getAttribute("scope") === "row" ? "" : headings[column] || "");
          column += Number(cell.getAttribute("colspan") || 1);
        }
      }
    }
  });
}

// Stock paid for in the dates, by where the money came from. Profit earned is not changed by buying stock (its cost
// counts when it is sold); money from the business is profit put back into stock, so what is left in hand is shown.
function Restocking({ paid, money }) {
  const business = Number(paid.business), own = Number(paid.own_money), investment = Number(paid.investment);
  if (!business && !own && !investment) return null;
  return <div className="restocking" role="note">
    {business > 0 && <p><b>Paid for stock from the business's money: {money(paid.business)}.</b> Profit left in hand after it: <b>{profitText(paid.profit_left, money)}</b>.
      The profit is still earned: it is now in the stock, and comes back when that stock is sold.</p>}
    {own > 0 && <p>Paid for stock from your own pocket: <b>{money(paid.own_money)}</b>. It is money you put into the business, so it does not come off the profit.</p>}
    {investment > 0 && <p>Paid for stock from your investment: <b>{money(paid.investment)}</b>. It came out of the investment, not the profit.</p>}
  </div>;
}

export function DashboardPage() {
  const { user } = useAuth();
  const organizationId = user?.organization?.id;
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState("");
  const [periodQuery, setPeriodQuery] = useState("");
  const refresh = useRef(() => {});
  const root = useRef(null);
  useColumnLabels(root);
  useEffect(() => {
    let active = true;
    let pending = false;
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const data = await api("/api/v1/inventory/dashboard/" + periodQuery);
        if (active) { setSnapshot(data); setError(""); }
      } catch (err) {
        if (active) setError(err.message);
      } finally { pending = false; }
    };
    refresh.current = load;
    void load();
    const visibleRefresh = () => { if (!document.hidden) void load(); };
    const timer = window.setInterval(visibleRefresh, 15000);
    window.addEventListener("focus", visibleRefresh);
    window.addEventListener("online", visibleRefresh);
    document.addEventListener("visibilitychange", visibleRefresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", visibleRefresh);
      window.removeEventListener("online", visibleRefresh);
      document.removeEventListener("visibilitychange", visibleRefresh);
    };
  }, [organizationId, periodQuery]);
  useLiveRefresh(() => refresh.current());
  const data = snapshot?.organization.id === organizationId ? snapshot : null;
  if (!data) return error ? <ErrorState message={error} retry={() => refresh.current()} /> : <Loading />;
  const { organization, today, inventory, orders, period_summary: period } = data;
  const money = (value) => value == null ? "Restricted" : `${organization.currency} ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const count = (value) => value == null ? "Restricted" : Number(value).toLocaleString();
  const units = data.business_units.filter(unit => unit.enabled);
  const trend = data.financial_trend;
  // Only when a month had stock found or missing, so every row still adds up to its profit.
  const stockColumn = trend.some(row => Number(row.stock_corrections || 0) !== 0);
  // The business uses investments and may see profit: their interest always shows, KSh 0 until a statement records some.
  const investing = (data.enabled_modules || []).includes("investments") && period?.profit != null;
  const interestColumn = investing || trend.some(row => Number(row.interest || 0) !== 0);
  const owedColumn = trend.some(row => Number(row.owed_profit || 0) !== 0);
  const monthName = (month) => new Date(`${month}-15T12:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" });
  const cards = (rows) => <div className="metrics">{rows.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}</div>;
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const on = (module) => (data.enabled_modules || []).includes(module);
  const owner = data.owner_summary;
  const ever = owner?.all_time;
  const owed = data.receivables && !data.receivables.restricted ? data.receivables.outstanding : owner?.customers_owe;
  // Today's key figures first, each one a link to where it is dealt with.
  const kpis = [
    // The dashboard brings together only each part's profit since the start; each part's money is on its own page.
    ever?.profit != null && ["Profit so far, every part together", profitText(ever.profit, money),
      [units.filter(unit => !unit.restricted && unit.all_time?.profit != null).map(unit => `${unit.name} ${profitText(unit.all_time.profit, money)}`).join(" · "),
        (investing || Number(ever.interest || 0)) && `interest on investments ${money(ever.interest || 0)}`,
        Number(ever.owed_profit || 0) > 0 && `${money(ever.owed_profit)} more when customers pay`, "money spent lowers it"].filter(Boolean).join(" · "), "/admin/reports", Number(ever.profit) < 0 ? "loss" : "profit"],
    owed != null && Number(owed) > 0 && ["Customers owe you", money(owed), "Sold, not yet paid", "/admin/sales-history"],
    !inventory.restricted && ["Products running low", count(inventory.low_stock), `Of ${count(inventory.total_skus)} products`, "/admin/products", Number(inventory.low_stock) > 0 ? "warn" : null],
  ].filter(Boolean);
  const actions = [
    on("pos") && can("commerce.add_sale") && ["/admin/pos", "Record a sale", true],
    on("inventory") && can("inventory.add_stockreceipt") && ["/admin/quick-receive", "Receive stock"],
    on("inventory") && can("catalog.view_product") && ["/admin/product-lookup", "Product lookup"],
    on("rooms") && can("hotel.view_stay") && ["/admin/rooms", "Front desk", !on("pos")],
    on("services") && can("cyber.view_cyberjob") && ["/admin/cyber", "Service desk"],
    on("menu") && can("hotel.add_kitchenuse") && ["/admin/kitchen", "Kitchen use"],
    can("accounting.add_expense") && ["/admin/expenses", "Record money spent"],
    can("accounting.view_profit") && ["/admin/reports", "Full reports"],
  ].filter(Boolean);
  const periodForm = period && <form className="reportPeriod" onSubmit={event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPeriodQuery("?" + new URLSearchParams({ start: form.get("start"), end: form.get("end") }));
  }}>
    <label>Date range<select aria-label="Date range" defaultValue="current-month" onChange={event => {
      const preset = event.target.value;
      if (preset === "custom") return;
      const end = new Date(data.business_date + "T12:00:00Z");
      const start = new Date(end);
      if (preset === "current-month") start.setUTCDate(1);
      if (preset === "last-seven-days") start.setUTCDate(start.getUTCDate() - 6);
      if (preset === "current-year") { start.setUTCMonth(0, 1); }
      if (preset === "last-month") { end.setUTCDate(0); start.setUTCFullYear(end.getUTCFullYear(), end.getUTCMonth(), 1); }
      event.target.form.elements.start.value = start.toISOString().slice(0, 10);
      event.target.form.elements.end.value = end.toISOString().slice(0, 10);
    }}><option value="current-month">Current month</option><option value="last-seven-days">Last 7 days</option><option value="last-month">Last month</option><option value="current-year">Current year</option><option value="custom">Custom dates</option></select></label>
    <label>From<input type="date" name="start" onChange={event => { event.target.form.querySelector("select").value = "custom"; }} required defaultValue={period.start} max={data.business_date} /></label>
    <label>To<input type="date" name="end" onChange={event => { event.target.form.querySelector("select").value = "custom"; }} required defaultValue={period.end} max={data.business_date} /></label>
    <button type="submit">Apply dates</button>
  </form>;
  return <div className="businessDashboard" ref={root}>
    <header className="dashHeader">
      <div className="dashHeaderTitle">
        <span className="eyebrow">{organization.business_type.replaceAll("_", " ")} · Business overview</span>
        <h1>{organization.name}</h1>
        <p>{data.business_date} · {user?.branch?.name || "Selected branch"}{units.length ? ` · ${units.map(unit => unit.name).join(" · ")}` : ""}</p>
      </div>
      <div className="dashHeaderLive">
        <p role="status">{error ? "Can't update right now — showing the last figures." : "Updates by itself every 15 seconds."} Last updated {new Date(data.generated_at).toLocaleTimeString(undefined, { timeZone: organization.timezone, hour: "2-digit", minute: "2-digit" })}</p>
        <button type="button" className="secondary" onClick={() => refresh.current()}><RefreshCw size={16} aria-hidden="true" /> Refresh now</button>
      </div>
      {actions.length > 0 && <nav className="dashActions" aria-label="Quick actions">
        {actions.map(([href, label, main]) => <a key={href} href={href} className={main ? "main" : undefined}>{label}</a>)}
      </nav>}
    </header>
    {error && <ErrorState message={error} retry={() => refresh.current()} />}
    {on("inventory") && can("catalog.view_product") && <StockQuickSearch />}
    <InvestmentReminder />
    <CommissionReminder />
    <section className="dashKpis" aria-label="Where the business has reached">
      {kpis.map(([label, value, detail, href, tone]) => {
        const body = <><span>{label}</span><strong>{value}</strong><small>{detail}</small></>;
        return href ? <a key={label} href={href} className={`dashKpi${tone ? ` ${tone}` : ""}`}>{body}</a> : <article key={label} className={`dashKpi${tone ? ` ${tone}` : ""}`}>{body}</article>;
      })}
    </section>

    <div className="dashColumns">
      <div className="dashMain">
        <PartsProfit units={units} total={ever?.profit} interest={ever?.interest} investing={investing} money={money} />
        {period && <section className="financialTrend" aria-labelledby="profit-loss-title">
          <h2 id="profit-loss-title">How the business is doing</h2>
          <p className="muted">Pick the dates to look at. A sale counts on the day you make it, even if the customer pays later.</p>
          {periodForm}
          <p className="muted">Showing {period.start} to {period.end}. {data.financial_scope === "permitted_operations" ? "Only the parts of the business you have access to are included." : ""}</p>
          {period.profit != null && <p className="profitSum"><b>{profitSum({ sales: period.revenue, cost: period.cogs, expenses: period.expenses, stock: period.stock_corrections, interest: period.interest, owed: period.owed_profit, profit: period.profit, investing }, money)}</b></p>}
          {period.restocking && <Restocking paid={period.restocking} money={money} />}
          {data.mpesa_unpaid && <div className="mpesaUnpaid" role="note">
            <p><b>M-Pesa commission not paid yet: about {money(data.mpesa_unpaid.amount)}</b> earned in {data.mpesa_unpaid.months.join(" and ")}, worked out from the
              commission balance readings. Safaricom pays it early the next month; it is added to the books when you record the payment on the Commission page.</p>
            <p>Profit or loss with it: <b>{profitText(data.mpesa_unpaid.profit_with, money)}</b></p>
          </div>}
          {!data.comparison && cards([["Stock bought from suppliers", money(period.purchases)], ["Stock you already had, entered at its cost", money(period.opening_stock)], ["Sales", money(period.revenue)], ["What the sold items cost you", money(period.cogs)], ["Profit before running costs", profitText(period.gross_profit, money)], ["Running costs (expenses)", money(period.expenses)], ...(Number(period.stock_corrections || 0) ? [["Stock found or missing in counts", stockText(period.stock_corrections, money)]] : []), ...(investing || Number(period.interest || 0) ? [["Interest on investments, after fees", interestText(period.interest, money)]] : []), ...(Number(period.owed_profit || 0) ? [["Profit in sales not paid for yet", owedText(period.owed_profit, money)]] : []), ["Profit received", profitText(period.profit, money)]])}
          <h3>Running costs</h3>
          {period.expenses == null ? <p>You don't have access to running costs.</p> : data.expense_breakdown?.length
            ? <div className="trendTable"><table><caption>Running costs by type</caption><thead><tr><th scope="col">Type</th><th scope="col">Part of the business</th><th scope="col">Amount</th></tr></thead><tbody>{data.expense_breakdown.map(row => <tr key={`${row.category}-${row.business_unit}`}><th scope="row">{row.category}</th><td>{data.business_units.find(unit => unit.key === row.business_unit)?.name || row.business_unit}</td><td>{money(row.amount)}</td></tr>)}</tbody><tfoot><tr><th scope="row" colSpan="2">Total</th><td>{money(period.expenses)}</td></tr></tfoot></table></div>
            : <p className="muted">No running costs recorded for these dates.</p>}
        </section>}
        {can("commerce.view_sale") && can("accounting.view_profit") && <SalesProfits money={money} timezone={organization.timezone}
          refreshKey={`${today.sales}-${today.revenue}`} />}
        <PeriodComparison data={data} money={money} />
        <BusinessAnalysis data={data} money={money} />
        {data.performance && <CollectionsPanel data={data} money={money} />}
      </div>

      <aside className="dashSide" aria-label="Money and stock now">
        {/* Only the parts' profit is brought together here; each part's own money, sales and costs are on its page. */}
        {units.length > 1 && <section className="dashCard"><h2>Each part's own figures</h2>
          <p className="muted">Each part keeps its own money, sales and costs on its page. Only their profit is added up here.</p>
          <ul className="dashPartLinks">{units.filter(unit => !unit.restricted).map(unit => <li key={unit.key}>
            <a href={{ SHOP: "/admin/sales-history", CYBER: "/admin/cyber", MPESA: "/admin/mpesa" }[unit.key]}>{unit.name}</a></li>)}</ul>
        </section>}
        {data.performance && <InShort data={data} money={money} />}
        {data.performance && <OwedPanels data={data} money={money} />}
        {!inventory.restricted && <section className="dashCard"><h2>Stock on your shelves</h2>
          <dl className="dashList">
            {[["Items on the shelves", count(inventory.physical)], ["Free to sell", count(inventory.available)], ["Products running low", count(inventory.low_stock)],
              ["Value (what you paid)", money(inventory.cost)], ["Value at selling price", money(inventory.retail)], ["Extra if all sells at full price", money(inventory.potential_margin)]]
              .map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
          </dl>
          <p className="muted">The extra is not profit until the items are actually sold.</p>
        </section>}
        {!orders.restricted && (Number(orders.awaiting_payment) > 0 || Number(orders.awaiting_fulfillment) > 0) && <section className="dashCard"><h2>Online orders needing attention</h2>
          <dl className="dashList"><div><dt>Waiting for payment</dt><dd>{count(orders.awaiting_payment)}</dd></div><div><dt>Paid, to pack or collect</dt><dd>{count(orders.awaiting_fulfillment)}</dd></div></dl>
        </section>}
        <ChamaDashboardCard />
      </aside>
    </div>

    <section className="dashMore" aria-labelledby="dash-more-title">
      <h2 id="dash-more-title">More detail</h2>
      {data.performance && <details><summary>Best sellers, item by item</summary><BestSellers data={data} money={money} /></details>}
      {data.recent_entries && <details><summary>Latest money in and out</summary><RecentEntries data={data} money={money} /></details>}
      <details><summary>Month by month</summary>
        <section className="financialTrend"><p className="muted">The last 12 months, with this month so far. Corrections count in the month they were made.</p>
          {!trend.length ? <p>No financial reporting operations are available to your account.</p> :
            <div className="trendTable"><table><caption>Each month ({organization.currency})</caption><thead><tr>{["Month", "Sales", "Stock bought", "What the sold items cost you", "Running costs", ...(stockColumn ? ["Stock found or missing"] : []), ...(interestColumn ? ["Interest on investments"] : []), ...(owedColumn ? ["Profit still owed by customers"] : []), "Profit received"].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{trend.map(row => <tr key={row.month}><th scope="row">{monthName(row.month)}</th>{[money(row.sales), money(row.purchases), money(row.cogs), money(row.expenses), ...(stockColumn ? [stockText(row.stock_corrections, money)] : []), ...(interestColumn ? [interestText(row.interest, money)] : []), ...(owedColumn ? [owedText(row.owed_profit, money)] : []), profitText(row.profit, money)].map((value, index) => <td key={index}>{value}</td>)}</tr>)}</tbody></table></div>}
        </section>
      </details>
      {data.records && <details><summary>Everything recorded so far</summary><RecordsSummary records={data.records} money={money} /></details>}
      <details><summary>How to read these figures</summary><div className="callout"><div>
        <p><b>Sales</b> is what customers were charged for what you sold, after discounts and any price corrections, whether they have paid yet or not.</p>
        <p><b>What the sold items cost you</b> is the buying price you paid for exactly those items, so profit is only counted on what was actually sold.</p>
        <p><b>Stock bought</b> is not taken off profit when you buy it. It stays on your shelves as stock until it is sold, and only then does its cost count.</p>
        <p><b>Running costs</b> are things like rent, wages and transport that you record under Money spent.</p></div></div></details>
    </section>
  </div>;
}
