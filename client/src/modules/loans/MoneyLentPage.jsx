import { Paged } from "../../components/Pager";
import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { TextArea } from "../../components/forms/TextBox";

const METHODS = [["CASH", "Cash"], ["MPESA", "Lipa na M-Pesa (till)"], ["BANK", "Bank"], ["OTHER", "Other"]];
// The owner's own money is not in the business's till, so its ways are plain.
const OWN_METHODS = [["CASH", "Cash"], ["MPESA", "M-Pesa"], ["BANK", "Bank"], ["OTHER", "Other"]];
const methodName = (value, own) => Object.fromEntries(own ? OWN_METHODS : METHODS)[value] || value;
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const date = (value) => (value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const today = () => new Date().toLocaleDateString("en-CA");
const STATUS = { OUTSTANDING: "Owing", PARTLY_REPAID: "Partly repaid", OVERDUE: "Overdue", REPAID: "Repaid", CANCELLED: "Cancelled" };

// Lend money: whose money it is (the owner is asked every time), who, how much, how it was handed over, and when it is
// due back. The business's money leaves its place straight away; the owner's own money never touches the business.
function LendForm({ canLendOwn, onSaved, onCancel }) {
  const [whose, setWhose] = useState(canLendOwn ? "" : "BUSINESS");
  const own = whose === "OWN";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = { ...Object.fromEntries(new FormData(event.currentTarget)), whose };
    if (!(await confirmAction({ title: `Lend ${money(values.amount)} ${own ? "of your own money " : ""}to ${values.borrower_name}?`,
      text: own ? `It is your own money, so the business's cash and figures don't change. It is due back to you on ${date(values.due_date)}.`
        : `It comes out of the business's ${methodName(values.method).toLowerCase()} now and is due back on ${date(values.due_date)}.`,
      confirmButtonText: "Record loan" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/accounting/loans/", { method: "POST", body: JSON.stringify({ ...values, idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)}>
      <h2>Lend money</h2>
      {canLendOwn && (
        <fieldset disabled={busy} className="loanWhose">
          <legend>Whose money are you lending?</legend>
          <label><input type="radio" name="whose_choice" value="BUSINESS" required checked={whose === "BUSINESS"} onChange={() => setWhose("BUSINESS")} />
            {" "}The business's money <small className="muted">(from its cash drawer, till or bank; the business is owed it)</small></label>
          <label><input type="radio" name="whose_choice" value="OWN" required checked={own} onChange={() => setWhose("OWN")} />
            {" "}My own money <small className="muted">(kept out of the business; only you see it)</small></label>
        </fieldset>
      )}
      <fieldset disabled={busy || !whose} className="loanFields">
        <FormField label="Borrower's name" name="borrower_name" required minLength={2} maxLength={120} autoComplete="off" />
        <FormField label="Phone number (optional)" name="borrower_phone" type="tel" maxLength={30} autoComplete="off" />
        <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" min="1" step="0.01" required />
        <FormField label={own ? "Handed over by" : "Paid out from"}>
          <select name="method" defaultValue="CASH">{(own ? OWN_METHODS : METHODS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </FormField>
        <FormField label="Date lent" name="lent_on" type="date" max={today()} defaultValue={today()} required />
        <FormField label="Agreed payback date" name="due_date" type="date" min={today()} required />
        <FormField label="Note (optional)"><TextArea name="notes" maxLength={500} placeholder="e.g. school fees, to be paid back in two parts" /></FormField>
      </fieldset>
      <div className="actionRow">
        <button disabled={busy || !whose}>Record loan</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the loan." message={error} />
    </form>
  );
}

// Money coming back: confirmed as received when saved. An M-Pesa repayment needs its code, to check against your messages.
function RepayForm({ loan, onSaved, onCancel }) {
  const own = loan.whose === "OWN";
  const [method, setMethod] = useState("CASH");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: `Confirm ${money(values.amount)} received from ${loan.borrower_name}?`,
      text: Number(values.amount) >= Number(loan.outstanding) ? "This clears the loan." : `${money(Number(loan.outstanding) - Number(values.amount))} will still be owed.`,
      confirmButtonText: "Confirm received" }))) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/accounting/loans/${loan.id}/repay/`, { method: "POST", body: JSON.stringify({ ...values, idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="loanRepay" onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy} className="loanFields">
        <FormField label={`Amount paid back (${businessCurrency()})`} name="amount" type="number" min="0.01" max={loan.outstanding} step="0.01"
          defaultValue={Number(loan.outstanding)} required />
        <FormField label="Received by">
          <select name="method" value={method} onChange={(event) => setMethod(event.target.value)}>
            {(own ? OWN_METHODS : METHODS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </FormField>
        <FormField label={method === "MPESA" && !own ? "M-Pesa code" : "Reference (optional)"} name="reference" maxLength={120}
          required={method === "MPESA" && !own} autoComplete="off" />
      </fieldset>
      <div className="actionRow">
        <button disabled={busy}>Confirm money received</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the repayment." message={error} />
    </form>
  );
}

function LoanCard({ loan, canRepay, canCorrect, isOwner, onChanged }) {
  const own = loan.whose === "OWN";
  const [repaying, setRepaying] = useState(false);
  const [error, setError] = useState("");
  const open = !["REPAID", "CANCELLED"].includes(loan.status);
  const correct = async (title, text, path) => {
    const values = await askForm({ title, text, confirmButtonText: "Confirm correction",
      fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. entered twice" }] });
    if (!values) return;
    const { reason } = values;
    setError("");
    try {
      await api(path, { method: "POST", body: JSON.stringify({ reason }) });
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  };
  const live = loan.repayments.filter((r) => !r.reversed_at);
  // Recorded as the business's money but it was the owner's own: the business gets back what was lent, gives back what
  // was repaid into it, and the loan stays here as the owner's own.
  const makeOwn = async () => {
    const back = Number(loan.amount) - Number(loan.repaid);
    if (!(await confirmAction({ title: `Was the ${money(loan.amount)} lent to ${loan.borrower_name} your own money?`,
      text: loan.status === "CANCELLED" ? "The loan moves to your own money."
        : `It comes out of the business's books: ${back > 0 ? `${money(back)} goes back into the business's ${methodName(loan.method).toLowerCase()} (what was lent, less what came back into it)`
          : back < 0 ? `${money(-back)} comes out of the business's places (paid back to it, more than was lent)` : "the business's money doesn't change (all of it was paid back into the business)"}, and what is still owed is owed to you.`,
      confirmButtonText: "Yes, it was my own money" }))) return;
    setError("");
    try {
      await api(`/api/v1/accounting/loans/${loan.id}/own/`, { method: "POST", body: "{}" });
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <li className={`loanCard ${loan.status.toLowerCase()}`}>
      <header className="loanCardHead">
        <div>
          <h3>{loan.borrower_name}</h3>
          <p className="muted">{[own ? "your own money" : "business money", loan.borrower_phone, `lent ${date(loan.lent_on)} by ${methodName(loan.method, own).toLowerCase()}`, loan.recorded_by && `recorded by ${loan.recorded_by}`].filter(Boolean).join(" · ")}</p>
        </div>
        <span className={`loanStatus ${loan.status.toLowerCase()}`}>{STATUS[loan.status]}{loan.days_overdue ? ` · ${loan.days_overdue} day${loan.days_overdue === 1 ? "" : "s"} late` : ""}</span>
      </header>
      <dl className="loanFigures">
        <div><dt>Lent</dt><dd>{money(loan.amount)}</dd></div>
        <div><dt>Paid back</dt><dd>{money(loan.repaid)}</dd></div>
        <div><dt>Still owed</dt><dd><strong>{money(loan.outstanding)}</strong></dd></div>
        <div><dt>Due back</dt><dd className={loan.status === "OVERDUE" ? "loanLate" : undefined}>{date(loan.due_date)}</dd></div>
      </dl>
      {loan.notes && <p className="loanNote">{loan.notes}</p>}
      {loan.cancelled_at && <p className="muted">Cancelled: {loan.cancel_reason}</p>}
      {loan.repayments.length > 0 && (
        <table className="loanRepayments">
          <caption>Repayments</caption>
          <thead><tr><th>Date</th><th>Amount</th><th>By</th><th>Reference</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
          <tbody>{loan.repayments.map((r) => (
            <tr key={r.id} className={r.reversed_at ? "muted" : undefined}>
              <td>{date(r.received_on)}</td>
              <td>{money(r.amount)}{r.reversed_at && <small> · reversed ({r.reverse_reason})</small>}</td>
              <td>{methodName(r.method, own)}</td>
              <td>{r.reference || "—"}</td>
              <td>{!r.reversed_at && canCorrect && <button type="button" className="secondary" onClick={() => void correct(
                `Reverse the ${money(r.amount)} repayment?`, `${loan.borrower_name} will owe it again.`, `/api/v1/accounting/loans/repayments/${r.id}/reverse/`)}>Reverse</button>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {open && (repaying
        ? <RepayForm loan={loan} onCancel={() => setRepaying(false)} onSaved={async () => { setRepaying(false); await onChanged(); }} />
        : <div className="actionRow">
          {canRepay && <button type="button" onClick={() => setRepaying(true)}>Record repayment</button>}
          {canCorrect && !live.length && <button type="button" className="secondary" onClick={() => void correct(
            `Cancel the loan to ${loan.borrower_name}?`, own ? "Use this only if it was recorded by mistake." : `Use this only if it was recorded by mistake: ${money(loan.amount)} goes back into your ${methodName(loan.method).toLowerCase()}.`,
            `/api/v1/accounting/loans/${loan.id}/cancel/`)}>Cancel loan</button>}
          {isOwner && !own && <button type="button" className="secondary" onClick={() => void makeOwn()}>It was my own money</button>}
        </div>)}
      {!open && isOwner && !own && loan.status === "REPAID" && <div className="actionRow">
        <button type="button" className="secondary" onClick={() => void makeOwn()}>It was my own money</button></div>}
      <FormError title="Could not change the loan." message={error} />
    </li>
  );
}

export function MoneyLentPage() {
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [lending, setLending] = useState(false);
  const load = async () => {
    try {
      setData(await api("/api/v1/accounting/loans/"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  // Overdue first, then whoever is due back soonest.
  const isOwner = Boolean(data.can_lend_own);
  const settledStatus = (loan) => ["REPAID", "CANCELLED"].includes(loan.status);
  const owing = (whose) => data.loans.filter((loan) => (loan.whose || "BUSINESS") === whose && !settledStatus(loan))
    .sort((a, b) => (b.status === "OVERDUE") - (a.status === "OVERDUE") || a.due_date.localeCompare(b.due_date));
  const owed = owing("BUSINESS");
  const ownOwed = owing("OWN");
  const settled = data.loans.filter(settledStatus);
  const card = (loan) => <LoanCard key={loan.id} loan={loan} canRepay={can("accounting.add_loanrepayment")}
    canCorrect={can("accounting.reverse_cashentry")} isOwner={isOwner} onChanged={load} />;
  return (
    <>
      <h1>Money lent</h1>
      <p className="muted">The business's money you lend comes out of its cash straight away and is owed back to the business. It is not an expense, so profit does not change.
        {isOwner && " Your own money lent is kept here only for you to remember; it never touches the business's money or figures."}</p>
      <div className="loanSummary">
        <p>Owed to the business: <strong>{money(data.total_outstanding)}</strong>{data.overdue > 0 && <span className="loanLate"> · {data.overdue} overdue</span>}</p>
        {isOwner && Number(data.own_outstanding) > 0 && <p>Owed to you (your own money): <strong>{money(data.own_outstanding)}</strong>
          {data.own_overdue > 0 && <span className="loanLate"> · {data.own_overdue} overdue</span>}</p>}
        {can("accounting.add_loan") && !lending && <button type="button" onClick={() => setLending(true)}>Lend money</button>}
      </div>
      {lending && <LendForm canLendOwn={isOwner} onCancel={() => setLending(false)} onSaved={async () => { setLending(false); await load(); }} />}
      <section aria-labelledby="owed-heading">
        <h2 id="owed-heading">Business money, still owed ({owed.length})</h2>
        {owed.length ? <Paged rows={owed} noun="loans">{(rows) => <ul className="loanList">{rows.map(card)}</ul>}</Paged> : <Empty>Nobody owes the business borrowed money.</Empty>}
      </section>
      {ownOwed.length > 0 && (
        <section aria-labelledby="own-owed-heading">
          <h2 id="own-owed-heading">Your own money, still owed ({ownOwed.length})</h2>
          <Paged rows={ownOwed} noun="loans">{(rows) => <ul className="loanList">{rows.map(card)}</ul>}</Paged>
        </section>
      )}
      {settled.length > 0 && (
        <details className="loanSettled">
          <summary>Repaid and cancelled ({settled.length})</summary>
          <Paged rows={settled} noun="loans">{(rows) => <ul className="loanList">{rows.map(card)}</ul>}</Paged>
        </details>
      )}
    </>
  );
}
