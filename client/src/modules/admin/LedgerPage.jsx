import { businessCurrency } from "../../core/organization/presentation";
import { useTranslation } from "../../core/i18n";
import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessParts } from "../../core/organization/MoneyModeChoice";
import { ErrorState, Loading } from "../../components/States";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";

export function LedgerPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [branch, setBranch] = useState(String(user?.branch?.id || ""));
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page) });
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    if (branch) params.set("branch", branch);
    setData(null); setError("");
    api(`/api/v1/accounting/ledger/reports/?${params}`, { signal: controller.signal })
      .then(setData).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [start, end, branch, page, revision]);
  const money = value => new Intl.NumberFormat(undefined, { style: "currency", currency: data?.currency || "KES" }).format(Number(value));
  return <>
    <h1>{t("reports")}</h1>
    <p>Sales count when supplied. Money received counts only after payment is confirmed.</p>
    <div className="filters">
      <label>From<input type="date" value={start} onChange={e => { setStart(e.target.value); setPage(1); }} /></label>
      <label>Through<input type="date" value={end} onChange={e => { setEnd(e.target.value); setPage(1); }} /></label>
      <label>Branch<select value={branch} onChange={e => { setBranch(e.target.value); setPage(1); }}>{user?.branches?.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
    </div>
    {error ? <ErrorState message={error} retry={() => setRevision(x => x+1)} /> : !data ? <Loading /> : <>
      <p role="note">{data.basis} These reports do not claim a complete opening balance sheet.</p>
      <section className="accountingPanel"><h2>Profit and loss</h2><p>Gross profit is sales less the cost of what you sold. Net profit also subtracts operating expenses.</p><dl>{Object.entries({ revenue: "Sales and commission", cogs: "Cost of goods and services sold", gross_profit: "Gross profit", expenses: "Operating expenses", net_profit: "Net profit" }).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{money(data.profit_loss[key])}</dd></div>)}</dl></section>
      <section className="accountingPanel"><h2>Balance sheet</h2><dl>{Object.entries({ assets: "What the business owns and is owed", liabilities: "What the business owes", equity: "Owner's recorded capital", retained_earnings: "Accumulated profit", difference: "Balance check (should be zero)" }).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{money(data.balance_sheet[key])}</dd></div>)}</dl></section>
      <section className="accountingPanel"><h2>Cash movement</h2><p>Includes recorded cash, bank, mobile money and agency float. Internal exchanges cancel out.</p><p>Opening {money(data.cash_movement.opening)} · Change {money(data.cash_movement.net_movement)} · Closing {money(data.cash_movement.closing)}</p></section>
      <section className="accountingPanel"><h2>Trial balance</h2><div className="trendTable"><table><thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead><tbody>{data.trial_balance.map(row => <tr key={row.account__code}><th scope="row">{row.account__code} {row.account__name}</th><td>{money(row.debit)}</td><td>{money(row.credit)}</td></tr>)}</tbody><tfoot><tr><th>Total</th><td>{money(data.debits)}</td><td>{money(data.credits)}</td></tr></tfoot></table></div></section>
      <section className="accountingPanel"><h2>Transactions behind these numbers</h2>{!data.journals.count && <p>No posted journals in this period.</p>}{data.journals.results.map(entry => <details key={entry.id}><summary>{entry.posting_date} · {entry.description}{entry.reversal_of ? " · Correction" : ""}</summary><p>Source: {entry.source_key}</p><table><thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead><tbody>{entry.lines.map((line, i) => <tr key={i}><th scope="row">{line.name}</th><td>{money(line.debit)}</td><td>{money(line.credit)}</td></tr>)}</tbody></table></details>)}<button disabled={page === 1} onClick={() => setPage(p => p-1)}>Previous</button><span> Page {page} </span><button disabled={page*50 >= data.journals.count} onClick={() => setPage(p => p+1)}>Next</button></section>
    </>}
  </>;
}

const EXPENSE_STATUS = { PAID: "Paid", PARTLY_PAID: "Partly paid", UNPAID: "Unpaid", CANCELLED: "Cancelled" };

export function ExpensesPage() {
  const { user: viewer } = useAuth();
  const parts = businessParts(viewer?.organization);
  const { t } = useTranslation();
  const [rows, setRows] = useState([]), [categories, setCategories] = useState([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [paid, setPaid] = useState(true);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [action, setAction] = useState(null);
  const [notice, setNotice] = useState(null);
  const load = async () => {
    const [expenses, groups] = await Promise.all([api('/api/v1/accounting/expenses/'), api('/api/v1/accounting/categories/')]);
    setRows(expenses); setCategories(groups);
  };
  useEffect(() => { load().catch(e => setError(e.message)); }, []);
  useLiveRefresh(load);
  const submit = async e => {
    e.preventDefault(); if (busy) return;
    const form = e.currentTarget, values = Object.fromEntries(new FormData(form));
    setBusy(true); setError("");
    try {
      let category = categories.find(c => c.name.toLowerCase() === values.category_name.trim().toLowerCase());
      if (!category) category = await api('/api/v1/accounting/categories/', { method: 'POST', body: JSON.stringify({ name: values.category_name.trim() }) });
      await api('/api/v1/accounting/expenses/', { method: 'POST', body: JSON.stringify({ category: category.id, business_unit: values.business_unit || 'SHOP',
        payment_method: values.payment_method || 'CASH', amount: values.amount, description: values.description, idempotency_key: key, paid,
        incurred_on: values.incurred_on || null, due_date: paid ? null : values.due_date || null }) });
      setKey(crypto.randomUUID()); form.reset(); setPaid(true); await load();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  const act = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true); setNotice(null);
    try {
      if (action.kind === "pay") {
        await api(`/api/v1/accounting/expenses/${action.row.id}/pay/`, { method: 'POST', body: JSON.stringify({ amount: values.amount, payment_method: values.payment_method, idempotency_key: action.key }) });
        setNotice({ kind: "success", text: `Payment recorded for ${action.row.description}.` });
      } else {
        await api(`/api/v1/accounting/expenses/${action.row.id}/cancel/`, { method: 'POST', body: JSON.stringify({ reason: values.reason }) });
        setNotice({ kind: "success", text: `${action.row.description} was cancelled and no longer counts.` });
      }
      setAction(null); await load();
    } catch (err) { setNotice({ kind: "error", text: err.message }); } finally { setBusy(false); }
  };
  const owed = rows.filter(r => r.status === 'UNPAID' || r.status === 'PARTLY_PAID').reduce((sum, r) => sum + Number(r.outstanding), 0);
  return <><h1>{t("expenses")}</h1>
    <p>Record running costs such as rent, wages, electricity or transport, paid now or owed. An expense counts once, in the period it relates to. Stock you buy to sell is recorded through Receive stock, not here.</p>
    <form onSubmit={submit}>
    <label>What was it for?<input name="description" required maxLength="160" /></label>
    <label>Category<input name="category_name" list="expense-categories" required maxLength="120" placeholder="Rent, transport, electricity…" /></label><datalist id="expense-categories">{categories.map(c => <option key={c.id} value={c.name} />)}</datalist>
    <label>Amount<input name="amount" type="number" min="0.01" step="0.01" required /></label>
    <label>Which period is it for?<input name="incurred_on" type="date" defaultValue={new Date().toISOString().slice(0, 10)} /></label>
    {parts.length > 1 ? <label>Part of the business<select name="business_unit">{parts.map((part) => <option key={part.key} value={part.key}>{part.name}</option>)}</select></label>
      : <input type="hidden" name="business_unit" value={parts[0].key} />}
    <fieldset className="checkList"><legend>Has it been paid?</legend>
      <label><input type="radio" name="paid_choice" checked={paid} onChange={() => setPaid(true)} /> Yes, paid now</label>
      <label><input type="radio" name="paid_choice" checked={!paid} onChange={() => setPaid(false)} /> No, to be paid later</label>
    </fieldset>
    {paid ? <label>Paid from<select name="payment_method"><option value="CASH">Cash</option><option value="BANK">Bank</option><option value="MPESA">Lipa na M-Pesa (till)</option><option value="OTHER">Other confirmed payment</option></select></label>
      : <label>Due date (optional)<input name="due_date" type="date" /></label>}
    <button disabled={busy}>{busy ? 'Recording…' : 'Record expense'}</button><FormError title="Could not record the expense." message={error} /></form>
    <h2>Recorded expenses</h2>
    {owed > 0 && <p><strong>Unpaid bills: {businessCurrency()} {owed.toFixed(2)}</strong></p>}
    {!rows.length ? <p>No expenses recorded yet.</p> : <div className="tableWrap"><table>
      <thead><tr><th>Date</th><th>Expense</th><th>Amount</th><th>Paid</th><th>Still owed</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        <td>{row.incurred_on}</td><td>{row.description}<br /><small className="muted">{row.category}</small></td>
        <td>{Number(row.amount).toFixed(2)}</td><td>{Number(row.paid).toFixed(2)}</td><td>{Number(row.outstanding).toFixed(2)}{row.due_date ? <><br /><small className="muted">due {row.due_date}</small></> : null}</td>
        <td>{EXPENSE_STATUS[row.status] || row.status}</td>
        <td>{row.status !== 'CANCELLED' && <>
          {Number(row.outstanding) > 0 && <button type="button" onClick={() => { setNotice(null); setAction({ kind: "pay", row, key: crypto.randomUUID() }); }}>Pay</button>}
          <button type="button" className="secondary" onClick={() => { setNotice(null); setAction({ kind: "cancel", row }); }}>Cancel</button>
        </>}</td>
      </tr>)}</tbody></table></div>}
    {action && <form className="formCard" onSubmit={act}>
      <h3>{action.kind === "pay" ? `Pay: ${action.row.description}` : `Cancel: ${action.row.description}`}</h3>
      {action.kind === "pay" ? <>
        <label>Amount<input name="amount" type="number" min="0.01" step="0.01" max={action.row.outstanding} defaultValue={action.row.outstanding} required /></label>
        <label>Paid from<select name="payment_method"><option value="CASH">Cash</option><option value="BANK">Bank</option><option value="MPESA">Lipa na M-Pesa (till)</option><option value="OTHER">Other confirmed payment</option></select></label>
      </> : <label>Why cancel it?<input name="reason" required maxLength="200" placeholder="e.g. recorded twice" /></label>}
      <button disabled={busy}>{action.kind === "pay" ? "Record payment" : "Cancel expense"}</button>
      <button type="button" className="secondary" onClick={() => setAction(null)}>Close</button>
    </form>}
    {notice && (notice.kind === "error" ? <FormError title="Could not complete that." message={notice.text} /> : <FormSuccess message={notice.text} />)}
  </>;
}
