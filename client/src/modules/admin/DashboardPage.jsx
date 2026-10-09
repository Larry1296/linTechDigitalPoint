import { AccountingPanels, PeriodComparison } from "./AccountingPanels";
import { profitSum, profitText, stockText } from "./plainMoney";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../core/auth/AuthContext";
import { api } from "../../core/api/client";
import { ErrorState, Loading } from "../../components/States";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { InvestmentReminder } from "../investments/InvestmentReminder";
import { CommissionReminder } from "../mpesa/CommissionReminder";
import { RecordsSummary } from "./RecordsSummary";
import { OwnerSummary } from "./OwnerSummary";
import { ChamaDashboardCard } from "../chama/ChamaDashboardCard";
import { BusinessAnalysis } from "./BusinessAnalysis";

export function DashboardPage() {
  const { user } = useAuth();
  const organizationId = user?.organization?.id;
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState("");
  const [periodQuery, setPeriodQuery] = useState("");
  const refresh = useRef(() => {});
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
  const { organization, today, inventory, cyber, mpesa, orders, period_summary: period } = data;
  const money = (value) => value == null ? "Restricted" : `${organization.currency} ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const count = (value) => value == null ? "Restricted" : Number(value).toLocaleString();
  const units = data.business_units.filter(unit => unit.enabled);
  const trend = data.financial_trend;
  // Only when a month had stock found or missing, so every row still adds up to its profit.
  const stockColumn = trend.some(row => Number(row.stock_corrections || 0) !== 0);
  const monthName = (month) => new Date(`${month}-15T12:00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" });
  const cards = (rows) => <div className="metrics">{rows.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}</div>;
  return <div className="businessDashboard">
    <section className="internalWelcome"><div className="internalWelcomeCopy">
      <span className="eyebrow">{organization.business_type.replaceAll("_", " ")} · Business overview</span>
      <h1>{organization.name}</h1>
      <p>{units.map(unit => unit.name).join(" · ") || "No reporting operations enabled"}</p>
      <p>Today is {data.business_date} · {user?.branch?.name || "Selected branch"}</p>
      <p role="status">{error ? "Can't update right now — showing the last figures." : "Updates by itself every 15 seconds."} Last updated {new Date(data.generated_at).toLocaleString(undefined, { timeZone: organization.timezone })}</p>
      <button className="button secondary" onClick={() => refresh.current()}>Refresh now</button>
    </div></section>
    {error && <ErrorState message={error} retry={() => refresh.current()} />}
    <OwnerSummary summary={data.owner_summary} money={money} />
    <nav className="accountingQuickActions" aria-label="Quick actions">
      {(data.enabled_modules || []).includes("inventory") && user?.permissions?.includes("catalog.view_product") && <a href="/admin/product-lookup">Product lookup</a>}
      {(data.enabled_modules || []).includes("inventory") && user?.permissions?.includes("inventory.add_stockreceipt") && <a href="/admin/quick-receive">Receive stock</a>}
      {user?.permissions?.includes("accounting.add_expense") && <a href="/admin/expenses">Record money spent</a>}
      {user?.permissions?.includes("accounting.view_profit") && <a href="/admin/reports">Full reports</a>}
      {(data.enabled_modules || []).includes("pos") && user?.permissions?.includes("commerce.add_sale") && <a href="/admin/pos">Record a sale</a>}
      {(data.enabled_modules || []).includes("services") && user?.permissions?.includes("cyber.view_cyberjob") && <a href="/admin/cyber">Service desk</a>}
    </nav>
    <InvestmentReminder />
    <CommissionReminder />
    <RecordsSummary records={data.records} money={money} />
    <ChamaDashboardCard />
    {period && <section className="financialTrend" aria-labelledby="profit-loss-title">
      <h2 id="profit-loss-title">How the business is doing</h2><p>Pick the dates you want to look at. A sale counts on the day you make it, even if the customer pays later. <a href="/admin/reports">Full reports</a> have the same figures in more detail.</p>
      <form className="reportPeriod" onSubmit={event => {
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
        }}><option value="current-month">Current month</option><option value="today">Today</option><option value="last-seven-days">Last 7 days</option><option value="last-month">Last month</option><option value="current-year">Current year</option><option value="custom">Custom dates</option></select></label>
        <label>From<input type="date" name="start" onChange={event => { event.target.form.querySelector("select").value = "custom"; }} required defaultValue={period.start} max={data.business_date} /></label>
        <label>To<input type="date" name="end" onChange={event => { event.target.form.querySelector("select").value = "custom"; }} required defaultValue={period.end} max={data.business_date} /></label>
        <button type="submit">Apply dates</button>
      </form>
      <p>Showing {period.start} to {period.end}. {data.financial_scope === "permitted_operations" ? "Only the parts of the business you have access to are included." : ""}</p>
      {period.profit != null && <p className="profitSum"><b>{profitSum({ sales: period.revenue, cost: period.cogs, expenses: period.expenses, stock: period.stock_corrections, profit: period.profit }, money)}</b></p>}
      {data.mpesa_unpaid && <div className="mpesaUnpaid" role="note">
        <p><b>M-Pesa commission not paid yet: about {money(data.mpesa_unpaid.amount)}</b> earned in {data.mpesa_unpaid.months.join(" and ")}, worked out from the
          commission balance readings. Safaricom pays it early the next month; it is added to the books when you record the payment on the Commission page.</p>
        <p>Profit or loss with it: <b>{profitText(data.mpesa_unpaid.profit_with, money)}</b></p>
      </div>}
      <PeriodComparison data={data} money={money} />
      {data.comparison ? cards([["Stock you already had, entered at its cost", money(period.opening_stock)], ["Profit before running costs", profitText(period.gross_profit, money)]]) : cards([["Stock bought from suppliers", money(period.purchases)], ["Stock you already had, entered at its cost", money(period.opening_stock)], ["Sales", money(period.revenue)], ["What the sold items cost you", money(period.cogs)], ["Profit before running costs", profitText(period.gross_profit, money)], ["Running costs (expenses)", money(period.expenses)], ...(Number(period.stock_corrections || 0) ? [["Stock found or missing in counts", stockText(period.stock_corrections, money)]] : []), ["Profit or loss", profitText(period.profit, money)]])}
      <div className="callout"><div><b>How to read these figures</b>
        <p><b>Sales</b> is what customers were charged for what you sold, after discounts and any price corrections, whether they have paid yet or not.</p>
        <p><b>What the sold items cost you</b> is the buying price you paid for exactly those items, so profit is only counted on what was actually sold.</p>
        <p><b>Stock bought</b> is not taken off profit when you buy it. It stays on your shelves as stock until it is sold, and only then does its cost count.</p>
        <p><b>Running costs</b> are things like rent, wages and transport that you record under Money spent.</p></div></div>
      <h3>Running costs</h3>
      {period.expenses == null ? <p>You don't have access to running costs.</p> : <>
        <p>Total running costs: <strong>{money(period.expenses)}</strong>.</p>
        {data.expense_breakdown?.length ? <div className="trendTable"><table><caption>Running costs by type</caption><thead><tr><th scope="col">Type</th><th scope="col">Part of the business</th><th scope="col">Amount</th></tr></thead><tbody>{data.expense_breakdown.map(row => <tr key={`${row.category}-${row.business_unit}`}><th scope="row">{row.category}</th><td>{data.business_units.find(unit => unit.key === row.business_unit)?.name || row.business_unit}</td><td>{money(row.amount)}</td></tr>)}</tbody><tfoot><tr><th scope="row" colSpan="2">Total</th><td>{money(period.expenses)}</td></tr></tfoot></table></div> : <p>No running costs recorded for these dates.</p>}
      </>}
    </section>}
    <BusinessAnalysis data={data} money={money} />
    <AccountingPanels data={data} money={money} />
    <section aria-label="Today's business totals"><h2>Today</h2>
      <p>M-Pesa deposits and withdrawals are customers' money, so they are not counted as sales.</p>
      {Number(today.revenue) < 0 && <p className="formNotice formNoticeInfo">Sales are below zero today because a price correction or return was recorded today for a sale made on an earlier day. The earlier day's sales are not changed; the correction is counted today.</p>}
      {cards([["Sales", money(today.revenue)], ["What the sold items cost you", money(today.cogs)], ["Running costs", money(today.expenses)], ...(Number(today.stock_corrections || 0) !== 0 ? [["Stock found or missing", stockText(today.stock_corrections, money)]] : []), ["Profit or loss", profitText(today.profit, money)], ["Sales made", count(today.sales)], ["Items sold", count(today.items_sold)]])}
    </section>
    <section className="unitBreakdown"><h2>Each part of the business today</h2><div className="unitBreakdownGrid">
      {units.map(unit => <article key={unit.key}><h3>{unit.name}</h3>{unit.restricted ? <p>Restricted</p> : <>
        <strong>{money(unit.revenue)}</strong><span>Sales</span><small>{profitText(unit.profit, money)} · Running costs {money(unit.expenses)}</small>
        {unit.key === "SHOP" && <p>Completed sales: {count(data.retail.sales)}</p>}
        {unit.key === "CYBER" && <p>Jobs in progress: {count(cyber.active_jobs)} · Ready to collect: {count(cyber.ready_jobs)} · New today: {count(cyber.jobs_today)}</p>}
        {unit.key === "MPESA" && <><p>Cash: {money(mpesa.cash)} · Float: {money(mpesa.float)}</p><p>Shifts open: {count(mpesa.open_sessions)} · Transactions today: {count(mpesa.transaction_count)}</p><p>Deposits: {money(mpesa.deposits)} · Withdrawals: {money(mpesa.withdrawals)}</p></>}
      </>}</article>)}
    </div></section>
    {!inventory.restricted && <section><h2>Stock on your shelves now</h2><p>The last figure is what you would make if every item sold at its full price. It is not profit until the items are actually sold.</p>{cards([["Products you stock", count(inventory.total_skus)], ["Items on the shelves", count(inventory.physical)], ["Items free to sell (not set aside for a customer)", count(inventory.available)], ["Products running low", count(inventory.low_stock)], ["Stock value (what you paid)", money(inventory.cost)], ["Stock value at selling price", money(inventory.retail)], ["Extra if it all sells at full price", money(inventory.potential_margin)]])}</section>}
    {!orders.restricted && <section><h2>Online orders needing attention</h2>{cards([["Waiting for payment", count(orders.awaiting_payment)], ["Paid, waiting to be packed or collected", count(orders.awaiting_fulfillment)]])}</section>}
    <section className="financialTrend"><h2>Month by month</h2><p>The last 12 months, with this month so far. Corrections count in the month they were made. The chart is under Analysis above.</p>
      {!trend.length ? <p>No financial reporting operations are available to your account.</p> : <>
        <div className="trendTable"><table><caption>Each month ({organization.currency})</caption><thead><tr>{["Month", "Sales", "Stock bought", "What the sold items cost you", "Running costs", ...(stockColumn ? ["Stock found or missing"] : []), "Profit or loss"].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{trend.map(row => <tr key={row.month}><th scope="row">{monthName(row.month)}</th>{[money(row.sales), money(row.purchases), money(row.cogs), money(row.expenses), ...(stockColumn ? [stockText(row.stock_corrections, money)] : []), profitText(row.profit, money)].map((value, index) => <td key={index}>{value}</td>)}</tr>)}</tbody></table></div>
      </>}
    </section>
  </div>;
}
