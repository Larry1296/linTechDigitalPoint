import { businessToday } from "../../core/organization/presentation";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { stockText } from "./plainMoney";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { TextBox } from "../../components/forms/TextBox";

const VIEWS = [["owner", "Summary"], ["units", "By business"], ["accounting", "Accounts"]];
const today = () => businessToday();
const monthStart = () => today().slice(0, 8) + "01";

export function useMoney(currency) {
  return (value) => new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "KES" }).format(Number(value || 0));
}

// A loss is written as "KSh 200 loss", never as a minus sign people may miss.
function Amount({ value, money, loss }) {
  const negative = loss ?? Number(value) < 0;
  return <span className={negative ? "lossText" : undefined}>{money(Math.abs(Number(value || 0)))}{negative ? " loss" : ""}</span>;
}

function Warnings({ items, money }) {
  if (!items?.length) return <p className="formNotice formNoticeSuccess">All checks passed: the records agree with each other and every item sold has a buying price.</p>;
  return <div className="formNotice formNoticeInfo" role="status"><strong>Some figures may not be complete yet:</strong>
    <ul className="reportWarnings">{items.map((w) => <li key={w.key}>{w.message}{w.amount !== undefined ? ` (${money(w.amount)})` : ""}{w.quantity !== undefined ? ` · ${Number(w.quantity)} unit(s)` : ""}</li>)}</ul>
  </div>;
}

function OwnerView({ summary, money }) {
  const cards = [["sales", "Sales"], ["money_received", "Money received"], ["stock_cost", "What the sold items cost you"], ["gross_profit", "Profit before running costs"],
    ["expenses", "Running costs"], ...(Number(summary.stock_corrections?.amount || 0) ? [["stock_corrections", "Stock found or missing"]] : []), ["net_profit", "Profit or loss"]];
  const p = summary.position;
  return <>
    <div className="reportCards">{cards.map(([key, label]) => <article key={key} className={key === "net_profit" ? "reportCard emphasis" : "reportCard"}>
      <span>{label}</span><strong>{key === "stock_corrections" ? stockText(summary[key].amount, money)
        : <Amount value={summary[key].amount} money={money} loss={key === "net_profit" || key === "gross_profit" ? Number(summary[key].amount) < 0 : false} />}</strong>
      <p className="muted">{summary[key].explain}</p>
    </article>)}</div>
    <section className="accountingPanel"><h2>Where the business stands today</h2>
      <dl className="reportPosition">
        <div><dt>Cash, bank and mobile money</dt><dd>{money(p.cash_and_bank)}</dd></div>
        <div><dt>Customers owe you</dt><dd>{money(p.customers_owe_you)}</dd></div>
        <div><dt>Stock value (at cost)</dt><dd>{money(p.stock_value)}</dd></div>
        <div><dt>You owe suppliers</dt><dd>{money(p.you_owe_suppliers)}</dd></div>
        <div><dt>Unpaid bills</dt><dd>{money(p.unpaid_bills)}</dd></div>
        <div><dt>Tax owed</dt><dd>{money(p.tax_owed)}</dd></div>
        {p.money_lent_out != null && Number(p.money_lent_out) !== 0 && <div><dt>Money lent out</dt><dd>{money(p.money_lent_out)}</dd></div>}
      </dl>
    </section>
    <section className="accountingPanel"><h2>For your KRA returns</h2>
      <p className="muted">Set the dates above to the period you are filing for. These figures help you fill in your iTax returns; this app does not file them for you.</p>
      <ul>
        <li><strong>Turnover Tax (TOT)</strong>, monthly, due by the 20th of the next month: declare your gross sales for the month. Use <strong>Sales</strong> above ({money(summary.sales.amount)}).</li>
        <li><strong>VAT (VAT3)</strong>, monthly by the 20th, only if you are VAT-registered: the VAT you charged customers is in <strong>Tax owed</strong>. VAT you paid on purchases is not tracked here, so take it from your suppliers' invoices.</li>
        <li><strong>Income tax</strong>, yearly (individuals by 30 June): use <strong>Profit or loss</strong> for the whole year ({money(summary.net_profit.amount)} for these dates).</li>
      </ul>
      <p className="muted">Resolve any warnings below before filing. Check current tax rates and thresholds on the KRA website or with a tax adviser.</p>
    </section>
    <Warnings items={summary.warnings} money={money} />
  </>;
}

function ProfitAndLoss({ pl, money }) {
  return <section className="accountingPanel"><h2>Profit or loss, by part of the business</h2>
    <table className="reportTable"><thead><tr><th scope="col">Part of the business</th><th scope="col">Sales</th><th scope="col">What the sold items cost you</th><th scope="col">Profit before running costs</th></tr></thead><tbody>
      {pl.units.map((unit) => <tr key={unit.key}>
        <th scope="row">{unit.name}</th>
        <td data-label="Sales">{money(unit.revenue)}</td>
        <td data-label="What the sold items cost you">− {money(unit.direct_costs)}</td>
        <td data-label="Profit before running costs"><Amount value={unit.gross_profit} money={money} /></td>
      </tr>)}
      <tr className="reportTotal"><th scope="row">All together</th><td data-label="Sales">{money(pl.revenue)}</td><td data-label="What the sold items cost you">− {money(pl.direct_costs)}</td><td data-label="Profit before running costs"><Amount value={pl.gross_profit} money={money} /></td></tr>
    </tbody></table>
    <h3>Running costs (shared by the whole business)</h3>
    {!pl.operating_expenses.length ? <p className="muted">No running costs recorded for these dates.</p> : <table className="reportTable"><tbody>
      {pl.operating_expenses.map((e) => <tr key={e.code}><th scope="row">{e.name}</th><td data-label="Amount">− {money(e.amount)}</td></tr>)}
      <tr className="reportTotal"><th scope="row">Total running costs</th><td data-label="Amount">− {money(pl.total_operating_expenses)}</td></tr>
    </tbody></table>}
    {Number(pl.stock_corrections || 0) !== 0 && <p>Stock found or missing when counting: <strong>{stockText(pl.stock_corrections, money)}</strong></p>}
    <p className="reportBottomLine">Profit or loss, before income tax: <strong><Amount value={pl.net_profit_before_tax} money={money} loss={pl.loss} /></strong></p>
  </section>;
}

function AccountLedger({ code, params, money, onClose }) {
  const [data, setData] = useState();
  const [error, setError] = useState("");
  useEffect(() => { api(`/api/v1/accounting/statements/accounts/${encodeURIComponent(code)}/?${params}`).then(setData).catch((e) => setError(e.message)); }, [code, params]);
  return <div className="shelfOverlay" role="presentation" onMouseDown={onClose}>
    <div className="shelfPanel" role="dialog" aria-modal="true" aria-label={`Account ${code}`} onMouseDown={(e) => e.stopPropagation()}>
      <header className="shelfPanelHeader"><div><span className="eyebrow">General ledger · {code}</span><h2>{data?.name || "Loading…"}</h2></div>
        <button type="button" className="shelfClose" onClick={onClose} aria-label="Close account">×</button></header>
      {error ? <ErrorState message={error} /> : !data ? <Loading /> : <>
        <p className="muted">Opening balance {money(data.opening)} · {data.count} posting(s)</p>
        <table className="reportTable"><thead><tr><th>Date</th><th>Source</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead>
          <tbody>{data.rows.map((r, i) => <tr key={i}><td data-label="Date">{r.date}</td><td data-label="Source">{r.description}<br /><small className="muted">{r.source}</small></td>
            <td data-label="Debit">{Number(r.debit) ? money(r.debit) : ""}</td><td data-label="Credit">{Number(r.credit) ? money(r.credit) : ""}</td><td data-label="Balance">{money(r.balance)}</td></tr>)}</tbody></table>
      </>}
    </div>
  </div>;
}

function SupplyCost({ row, onDone }) {
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true); setError("");
    try { await api(`/api/v1/inventory/lots/${row.lot}/cost/`, { method: "POST", body: JSON.stringify(values) }); onDone(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <form className="inlineForm" onSubmit={submit}>
    <label>Buying price for one<input name="unit_cost" type="number" min="0.01" step="0.01" required /></label>
    <label>Where does it come from?<TextBox name="reason" required maxLength="200" placeholder="e.g. found the supplier invoice" /></label>
    <button disabled={busy}>Save price</button>
    <FormError title="Could not save the price." message={error} />
  </form>;
}

function AccountingView({ data, money, params, reload, canSupplyCost }) {
  const [account, setAccount] = useState(null);
  const [costFor, setCostFor] = useState(null);
  const bs = data.balance_sheet;
  return <>
    <p className="formNotice formNoticeInfo">This tab lays the figures out the way an accountant or KRA expects (balance sheet, trial balance and so on). For day-to-day use, the <b>Summary</b> tab has the same numbers in plain words.</p>
    <Warnings items={data.warnings} money={money} />
    <ProfitAndLoss pl={data.profit_and_loss} money={money} />
    <section className="accountingPanel"><h2>Balance sheet</h2>
      {[["What the business owns", bs.assets, bs.total_assets], ["What the business owes", bs.liabilities, bs.total_liabilities], ["Owner's equity", bs.equity, bs.total_equity]].map(([title, rows, total]) =>
        <div key={title}><h3>{title}</h3><table className="reportTable"><tbody>{rows.map((r) => <tr key={r.code}><th scope="row"><button type="button" className="linkButton" onClick={() => setAccount(r.code)}>{r.name}</button></th><td data-label="Amount">{money(r.amount)}</td></tr>)}
          <tr className="reportTotal"><th scope="row">Total</th><td data-label="Amount">{money(total)}</td></tr></tbody></table></div>)}
      <p>Profit kept in the business: {money(bs.retained_earnings)} · {Number(bs.difference) === 0 ? "Balanced ✓" : <span className="lossText">Out of balance by {money(bs.difference)}</span>}</p>
    </section>
    <section className="accountingPanel"><h2>Trial balance</h2>
      <table className="reportTable"><thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead><tbody>
        {data.trial_balance.rows.map((r) => <tr key={r.code}><th scope="row"><button type="button" className="linkButton" onClick={() => setAccount(r.code)}>{r.code} · {r.name}</button></th><td data-label="Debit">{money(r.debit)}</td><td data-label="Credit">{money(r.credit)}</td></tr>)}
        <tr className="reportTotal"><th scope="row">Totals</th><td data-label="Debit">{money(data.trial_balance.debits)}</td><td data-label="Credit">{money(data.trial_balance.credits)}</td></tr>
      </tbody></table>
    </section>
    <section className="accountingPanel"><h2>Cash flow</h2><p className="muted">{data.cash_flow.note}</p>
      <table className="reportTable"><tbody>{data.cash_flow.rows.map((r) => <tr key={r.key}><th scope="row">{r.label}</th><td data-label="Amount">{money(r.amount)}</td></tr>)}
        <tr className="reportTotal"><th scope="row">Net change in cash</th><td data-label="Amount">{money(data.cash_flow.net)}</td></tr></tbody></table>
    </section>
    <section className="accountingPanel"><h2>Reconciliation</h2><p className="muted">Detailed records compared with the ledger. Any difference is shown with its likely cause.</p>
      <table className="reportTable"><thead><tr><th>Check</th><th>Records</th><th>Ledger</th><th>Difference</th></tr></thead><tbody>
        {data.reconciliation.map((r) => <tr key={r.key}><th scope="row">{r.label}{r.explanation && <><br /><small className="muted">{r.explanation}</small></>}</th>
          <td data-label="Records">{money(r.detail)}</td><td data-label="Ledger">{money(r.ledger)}</td>
          <td data-label="Difference">{r.reconciled ? "✓ Reconciled" : <span className="lossText">{money(r.difference)}</span>}</td></tr>)}
      </tbody></table>
    </section>
    <section className="accountingPanel"><h2>Customers owe you</h2>
      {!data.receivables.length ? <p className="muted">No customer balances.</p> : <table className="reportTable"><thead><tr><th>Sale</th><th>Customer</th><th>Due</th><th>Owed</th></tr></thead><tbody>
        {data.receivables.map((r) => <tr key={r.sale}><td data-label="Sale">{r.number}</td><td data-label="Customer">{r.customer}</td><td data-label="Due">{r.due_date || "—"}</td><td data-label="Owed">{money(r.owed)}</td></tr>)}</tbody></table>}
    </section>
    <section className="accountingPanel"><h2>You owe</h2>
      {!data.payables.suppliers.length && !data.payables.bills.length ? <p className="muted">Nothing owed.</p> : <table className="reportTable"><thead><tr><th>To</th><th>Reference</th><th>Owed</th></tr></thead><tbody>
        {data.payables.suppliers.map((r) => <tr key={`s${r.id}`}><td data-label="To">{r.name}</td><td data-label="Reference">Stock receipt {r.reference}</td><td data-label="Owed">{money(r.owed)}</td></tr>)}
        {data.payables.bills.map((r) => <tr key={`b${r.id}`}><td data-label="To">{r.name}</td><td data-label="Reference">{r.reference}{r.due_date ? ` · due ${r.due_date}` : ""}</td><td data-label="Owed">{money(r.owed)}</td></tr>)}
      </tbody></table>}
    </section>
    <section className="accountingPanel"><h2>Stock value</h2><p className="muted">Every delivery still on the shelves, at its own recorded cost (oldest is sold first).</p>
      {!data.stock_valuation.length ? <p className="muted">No stock on hand.</p> : <table className="reportTable"><thead><tr><th>Item</th><th>Delivery</th><th>Qty</th><th>Cost each</th><th>Value</th></tr></thead><tbody>
        {data.stock_valuation.map((r, i) => <tr key={i}><td data-label="Item">{r.item}<br /><small className="muted">{r.shelf}</small></td><td data-label="Delivery">{r.reference}<br /><small className="muted">{r.supplier || "—"}</small></td>
          <td data-label="Qty">{Number(r.quantity)}</td>
          <td data-label="Cost each">{r.uncosted ? <><span className="lossText">No buying price</span>{canSupplyCost && (costFor === r.lot ? <SupplyCost row={r} onDone={() => { setCostFor(null); reload(); }} /> : <button type="button" className="linkButton" onClick={() => setCostFor(r.lot)}>Supply buying price</button>)}</> : money(r.unit_cost)}</td>
          <td data-label="Value">{r.uncosted ? "—" : money(r.value)}</td></tr>)}</tbody></table>}
    </section>
    <p><Link to="/admin/reports/journals">See every record behind these numbers (for your accountant) →</Link></p>
    {account && <AccountLedger code={account} params={params} money={money} onClose={() => setAccount(null)} />}
  </>;
}

export function AccountingReportsPage() {
  const { user } = useAuth();
  const [view, setView] = useState("owner");
  const [start, setStart] = useState(monthStart());
  const [end, setEnd] = useState(today());
  const [branch, setBranch] = useState(String(user?.branch?.id || ""));
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const params = new URLSearchParams({ start, end, ...(branch ? { branch } : {}) }).toString();
  const reload = useCallback(() => setRevision((x) => x + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    api(`/api/v1/accounting/statements/?view=${view}&${params}`, { signal: controller.signal }).then(setData)
      .catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [view, params, revision]);
  // After a change anywhere, fetch the same report again quietly (no loading flash).
  useLiveRefresh(() => api(`/api/v1/accounting/statements/?view=${view}&${params}`).then((fresh) => { if (fresh?.view === view) setData(fresh); }));
  const money = useMoney(data?.currency);
  return <>
    <span className="eyebrow">Your business figures</span>
    <h1>Reports</h1>
    <p className="muted">Sales count when goods or services are delivered, even if unpaid. Money received is shown separately and is never counted as profit.</p>
    <div className="filters">
      <label>From<input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></label>
      <label>Through<input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></label>
      {user?.branches?.length > 1 && <label>Branch<select value={branch} onChange={(e) => setBranch(e.target.value)}>{user.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>}
    </div>
    <div className="tabs" role="tablist" aria-label="Report level">
      {VIEWS.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={view === key} className={view === key ? "active" : ""} onClick={() => setView(key)}>{label}</button>)}
    </div>
    {error ? <ErrorState message={error} retry={reload} /> : !data || data.view !== view ? <Loading /> : view === "owner" ? <OwnerView summary={data.summary} money={money} />
      : view === "units" ? <><ProfitAndLoss pl={data.profit_and_loss} money={money} /><Warnings items={data.warnings} money={money} /></>
        : <AccountingView data={data} money={money} params={params} reload={reload} canSupplyCost={user?.permissions?.includes("inventory.adjust_stock")} />}
  </>;
}
