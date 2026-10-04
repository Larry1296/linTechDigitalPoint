import { useEffect, useRef, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { InterestCalculator } from "./InterestCalculator";
import { earnings } from "./interest";

const BUSINESS = [["MPESA", "Lipa na M-Pesa (till)"], ["CASH", "Cash"], ["BANK", "Bank"], ["OTHER", "Other"]];
const AGENCY = [["AGENCY_CASH", "M-Pesa agency cash"], ["AGENCY_FLOAT", "M-Pesa agency float"]];
const sourceName = (value) => Object.fromEntries([...BUSINESS, ...AGENCY])[value] || value;
const KIND = { DEPOSIT: "Put in", WITHDRAWAL: "Taken out", INTEREST: "Interest", FEE: "Fees or loss" };
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const date = (value) => (value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const today = () => new Date().toLocaleDateString("en-CA");
const percent = (value) => `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })}%`;

function NewInvestmentForm({ onSaved, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const values = Object.fromEntries(new FormData(event.currentTarget));
      await api("/api/v1/accounting/investments/", { method: "POST", body: JSON.stringify({ ...values, annual_rate: values.annual_rate || null }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)}>
      <h2>Add an investment account</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Name of the fund or account" name="name" required minLength={2} maxLength={120} placeholder="e.g. Sanlam MMF" autoComplete="off" />
        <FormField label="Account number (optional)" name="account_number" maxLength={60} autoComplete="off" />
        <FormField label="Yearly interest rate it pays now (%)" name="annual_rate" type="number" min="0" max="100" step="0.001"
          placeholder="e.g. 13.25 — the annual yield in the fund's app or SMS" />
        <FormField label="Withholding tax on interest (%)" name="tax_rate" type="number" min="0" max="100" step="0.01" defaultValue="15" required />
        <FormField label="Note (optional)"><textarea name="notes" maxLength={500} placeholder="e.g. spare agency cash, withdraw takes 2 days" /></FormField>
      </fieldset>
      <div className="actionRow">
        <button disabled={busy}>Add account</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not add the account." message={error} />
    </form>
  );
}

// Money put in or taken out. Agency cash and float move through today's open shift, so the desk balances follow.
function MoveForm({ investment, kind, sessions, spare, preset, onSaved, onCancel }) {
  const putIn = kind === "DEPOSIT";
  const [source, setSource] = useState(preset?.source || "MPESA");
  const [amount, setAmount] = useState(preset?.amount ?? (putIn ? "" : String(Number(investment.value))));
  const available = (value) => spare.find((p) => p.method === value)?.expected;
  const short = putIn && available(source) != null && Number(amount) > Number(available(source));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const agency = source.startsWith("AGENCY_");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const where = sourceName(values.source).toLowerCase();
    if (!(await confirmAction({ title: putIn ? `Put ${money(values.amount)} into ${investment.name}?` : `Take ${money(values.amount)} out of ${investment.name}?`,
      text: putIn ? `It comes out of your ${where}. It is still your money, so profit does not change.` : `It goes back into your ${where}.`,
      confirmButtonText: putIn ? "Record money put in" : "Record money taken out" }))) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/accounting/investments/${investment.id}/move/`, { method: "POST",
        body: JSON.stringify({ ...values, kind, ...(values.session_id ? { session_id: Number(values.session_id) } : {}), idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="loanRepay" onSubmit={(event) => void submit(event)} aria-label={putIn ? "Put money in" : "Take money out"}>
      <fieldset disabled={busy} className="loanFields">
        <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" min="0.01" step="0.01"
          max={putIn ? undefined : investment.value} value={amount} onChange={(event) => setAmount(event.target.value)} required />
        <FormField label={putIn ? "Taken from" : "Paid into"}>
          <select name="source" value={source} onChange={(event) => setSource(event.target.value)}>
            {BUSINESS.map(([value, label]) => <option key={value} value={value}>
              {label}{putIn && available(value) != null ? ` · ${money(available(value))} expected` : ""}</option>)}
            {sessions.length > 0 && AGENCY.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </FormField>
        {agency && sessions.length > 1 && (
          <FormField label="M-Pesa outlet">
            <select name="session_id" required defaultValue="">
              <option value="" disabled>Choose the outlet</option>
              {sessions.map((s) => <option key={s.id} value={s.id}>{s.outlet} · cash {money(s.cash)} · float {money(s.float)}</option>)}
            </select>
          </FormField>
        )}
        {agency && sessions.length === 1 && <p className="muted">{sessions[0].outlet} now: cash {money(sessions[0].cash)} · float {money(sessions[0].float)}</p>}
        {agency
          ? <p className="muted">Agency money moves today, through the open shift.</p>
          : <FormField label="Date" name="occurred_on" type="date" max={today()} defaultValue={today()} required />}
        <FormField label="Transaction code or reference (optional)" name="reference" maxLength={120} autoComplete="off" />
        <FormField label="Note (optional)" name="note" maxLength={500} autoComplete="off" />
      </fieldset>
      {short && <p className="investWarning">That is more than the {money(available(source))} the app expects in your {sourceName(source).toLowerCase()}.
        Check the amount, or record any missing sales or starting money first.</p>}
      {!putIn && <p className="muted">Paying a supplier for stock? Record it when you receive the stock: choose
        “Paid the supplier now → from my investment”, so the withdrawal and the stock it paid for are linked.</p>}
      <div className="actionRow">
        <button disabled={busy}>{putIn ? "Record money put in" : "Record money taken out"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record it." message={error} />
    </form>
  );
}

// The fund's statement balance: anything above what the app expects is interest earned; below it, fees or a loss.
function StatementForm({ investment, onSaved, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const difference = Number(values.balance) - Number(investment.value);
    if (!(await confirmAction({ title: `Statement shows ${money(values.balance)}?`,
      text: difference > 0 ? `${money(difference)} will be recorded as interest earned.` : difference < 0 ? `${money(-difference)} will be recorded as fees or a loss.` : "This matches the app; nothing will be recorded.",
      confirmButtonText: "Record statement" }))) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/accounting/investments/${investment.id}/statement/`, { method: "POST", body: JSON.stringify({ ...values, idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="loanRepay" onSubmit={(event) => void submit(event)} aria-label="Record statement balance">
      <fieldset disabled={busy} className="loanFields">
        <FormField label={`Balance on the statement or app (${businessCurrency()})`} name="balance" type="number" min="0" step="0.01" required />
        <FormField label="Statement date" name="occurred_on" type="date" max={today()} defaultValue={today()} required />
      </fieldset>
      <p className="muted">The app expects {money(investment.value)}. The difference is recorded as interest (or fees if lower).</p>
      <div className="actionRow">
        <button disabled={busy}>Record statement</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the statement." message={error} />
    </form>
  );
}

// Once a month: the rate the fund quotes now and, if to hand, the balance on its statement or app.
function MonthlyCheckForm({ investment, month, onSaved, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const estimate = investment.estimate;
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const difference = values.balance === "" ? 0 : Number(values.balance) - Number(investment.value);
    if (!(await confirmAction({ title: `${investment.name}: ${percent(values.annual_rate)} a year for ${month}?`,
      text: values.balance === "" ? "Only the rate is recorded. Add the balance when you have the statement to record the interest."
        : difference > 0 ? `The balance is ${money(values.balance)}, so ${money(difference)} is recorded as interest earned.`
          : difference < 0 ? `The balance is ${money(values.balance)}, so ${money(-difference)} is recorded as fees or a loss.`
            : "The balance agrees with the app; only the rate is recorded.",
      confirmButtonText: "Record monthly check" }))) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/accounting/investments/${investment.id}/monthly/`, { method: "POST",
        body: JSON.stringify({ annual_rate: values.annual_rate, balance: values.balance === "" ? null : values.balance, note: values.note, idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="loanRepay" onSubmit={(event) => void submit(event)} aria-label="Monthly check">
      <h4 className="investFormTitle">Monthly check · {month}</h4>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Yearly rate it pays now (%)" name="annual_rate" type="number" min="0" max="100" step="0.001" required
          defaultValue={investment.current_rate ? Number(investment.current_rate.annual_rate) : undefined} placeholder="e.g. 13.25" />
        <FormField label={`Balance on the statement or app today (${businessCurrency()}, optional)`} name="balance" type="number" min="0" step="0.01"
          placeholder={estimate ? `About ${Number(estimate.value).toLocaleString()} expected` : undefined} />
        <FormField label="Note (optional)" name="note" maxLength={500} autoComplete="off" />
      </fieldset>
      <p className="muted">Use the annual yield shown in the fund's app, statement or SMS. The app records {money(investment.value)};
        {estimate ? ` with about ${money(estimate.net)} interest since ${date(estimate.since)}, expect around ${money(estimate.value)}.` : " a balance above that is interest earned."}</p>
      <div className="actionRow">
        <button disabled={busy}>Record monthly check</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the monthly check." message={error} />
    </form>
  );
}

function InvestmentCard({ investment, sessions, spare, preset, month, canMove, canCorrect, onChanged }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const card = useRef(null);
  useEffect(() => {
    if (!preset) return;
    setForm(preset.kind || "DEPOSIT");
    card.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [preset]);
  const done = async () => { setForm(null); await onChanged(); };
  const rate = investment.current_rate;
  const pace = rate ? earnings(investment.value, rate.annual_rate, investment.tax_rate) : null;
  const undo = async (m) => {
    const values = await askForm({ title: `Undo this ${KIND[m.kind].toLowerCase()} of ${money(m.amount)}?`,
      text: m.source ? `The money goes back to your ${sourceName(m.source).toLowerCase()}.` : "The investment's value goes back to what it was.",
      confirmButtonText: "Undo", fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. entered twice" }] });
    if (!values) return;
    setError("");
    try {
      await api(`/api/v1/accounting/investments/movements/${m.id}/undo/`, { method: "POST", body: JSON.stringify({ reason: values.reason }) });
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <li className={`loanCard${investment.check_due ? " investDue" : ""}`} ref={card}>
      <header className="loanCardHead">
        <div>
          <h3>{investment.name}</h3>
          {investment.account_number && <p className="muted">Account {investment.account_number}</p>}
        </div>
        {rate
          ? <span className="loanStatus investRate" title={`Recorded ${date(rate.recorded_on)}`}>{percent(rate.annual_rate)} a year · {rate.label}</span>
          : <span className="loanStatus overdue">No rate recorded</span>}
      </header>
      <dl className="loanFigures">
        <div><dt>Recorded value</dt><dd><strong>{money(investment.value)}</strong></dd></div>
        <div><dt>Put in</dt><dd>{money(investment.put_in)}</dd></div>
        <div><dt>Taken out</dt><dd>{money(investment.taken_out)}</dd></div>
        <div><dt>Interest earned</dt><dd>{money(investment.interest)}{Number(investment.fees) ? <small> · fees {money(investment.fees)}</small> : null}</dd></div>
        {investment.estimate && <div><dt>Estimated since {date(investment.estimate.since)}</dt>
          <dd>+ {money(investment.estimate.net)} <small>after {percent(investment.tax_rate)} tax</small></dd></div>}
        {investment.estimate && <div><dt>Estimated value today</dt><dd>{money(investment.estimate.value)}</dd></div>}
      </dl>
      {rate && Number(investment.value) > 0 && <p className="investEarning">At {percent(rate.annual_rate)}, {money(investment.value)} earns about{" "}
        <strong>{money(pace.day)} a day</strong> · {money(pace.month)} a month after tax.</p>}
      {investment.check_due && <p className="investWarning">{month}'s check is due: record the rate {investment.name} pays now
        {canMove ? " with “Monthly check” below." : ". Ask someone who manages investments to do it."}</p>}
      {investment.notes && <p className="loanNote">{investment.notes}</p>}
      {investment.movements.length > 0 && (
        <table className="loanRepayments">
          <caption>History</caption>
          <thead><tr><th>Date</th><th>What</th><th>Amount</th><th>From / to</th><th>Reference</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
          <tbody>{investment.movements.map((m) => (
            <tr key={m.id} className={m.reversed_at ? "muted" : undefined}>
              <td>{date(m.occurred_on)}</td>
              <td>{KIND[m.kind]}{m.statement_balance ? <small> · statement {money(m.statement_balance)}</small> : null}
                {m.purchase && <small className="investPurchase"> · paid for stock {m.purchase.receipt_number}{m.purchase.supplier && ` (${m.purchase.supplier})`}</small>}</td>
              <td>{money(m.amount)}{m.reversed_at && <small> · undone ({m.reverse_reason})</small>}</td>
              <td>{m.source ? sourceName(m.source) : "—"}</td>
              <td>{m.reference || m.note || "—"}</td>
              <td>{!m.reversed_at && canCorrect && <button type="button" className="secondary" onClick={() => void undo(m)}>Undo</button>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {investment.rates.length > 0 && (
        <details className="investRates">
          <summary>Monthly rates ({investment.rates.length})</summary>
          <table className="loanRepayments">
            <thead><tr><th>Month</th><th>Yearly rate</th><th>Balance seen</th><th>Recorded</th></tr></thead>
            <tbody>{investment.rates.map((r) => (
              <tr key={r.month}><td>{r.label}</td><td>{percent(r.annual_rate)}</td><td>{r.statement_balance != null ? money(r.statement_balance) : "—"}</td>
                <td>{date(r.recorded_on)}{r.recorded_by && ` · ${r.recorded_by}`}</td></tr>))}</tbody>
          </table>
        </details>
      )}
      {form === "MONTHLY" ? <MonthlyCheckForm investment={investment} month={month} onCancel={() => setForm(null)} onSaved={done} />
        : form === "DEPOSIT" || form === "WITHDRAWAL"
        ? <MoveForm key={preset?.nonce ?? form} investment={investment} kind={form} sessions={sessions} spare={spare}
          preset={form === "DEPOSIT" ? preset : null} onCancel={() => setForm(null)} onSaved={done} />
        : form === "STATEMENT"
          ? <StatementForm investment={investment} onCancel={() => setForm(null)} onSaved={done} />
          : canMove && <div className="actionRow">
            <button type="button" className={investment.check_due ? undefined : "secondary"} onClick={() => setForm("MONTHLY")}>Monthly check</button>
            <button type="button" onClick={() => setForm("DEPOSIT")}>Put money in</button>
            <button type="button" className="secondary" disabled={Number(investment.value) <= 0} onClick={() => setForm("WITHDRAWAL")}>Take money out</button>
            <button type="button" className="secondary" onClick={() => setForm("STATEMENT")}>Update from statement</button>
          </div>}
      <FormError title="Could not undo it." message={error} />
    </li>
  );
}

// Money the app expects in the till, drawer and bank: what could be moved into an investment.
function SpareMoney({ spare, investments, canMove, onInvest }) {
  const [target, setTarget] = useState(investments[0]?.id);
  const places = spare.filter((p) => Number(p.expected) > 0);
  return (
    <section className="panel investSpare" aria-labelledby="spare-heading">
      <header>
        <div>
          <h2 id="spare-heading">Money you could invest</h2>
          <p className="muted">What the app expects in each place now. Keep enough for change and the day's buying; invest the rest.</p>
        </div>
        {canMove && investments.length > 1 && <label>Into
          <select value={target} onChange={(event) => setTarget(Number(event.target.value))}>
            {investments.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </label>}
      </header>
      {places.length
        ? <ul>{places.map((p) => (
          <li key={p.method}>
            <span>{p.label}</span>
            <strong>{money(p.expected)}</strong>
            {canMove && investments.length > 0 &&
              <button type="button" className="secondary" onClick={() => onInvest({ id: target, source: p.method, amount: String(Number(p.expected)) })}>Invest</button>}
          </li>))}</ul>
        : <p className="muted">No spare money recorded in the till, drawer or bank right now.</p>}
    </section>
  );
}

export function InvestmentsPage() {
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [preset, setPreset] = useState(null);
  const load = async () => {
    try {
      setData(await api("/api/v1/accounting/investments/"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const canMove = can("accounting.add_investmentmovement");
  const spare = data.spare_money || [];
  const till = spare.find((p) => p.method === "MPESA");
  const due = data.investments.filter((i) => i.check_due);
  const rated = data.investments.find((i) => i.current_rate);
  return (
    <>
      <div className="loanSummary">
        <h1>Investments</h1>
        {can("accounting.add_investment") && !adding && <button type="button" onClick={() => setAdding(true)}>Add investment account</button>}
      </div>
      <p className="muted">Spare money kept in a money market fund (MMF) or similar. Putting money in or taking it out is still your money,
        so profit does not change; only the interest it earns is income.</p>
      <div className="metrics investMetrics">
        <article><span>Invested now</span><strong>{money(data.total_value)}</strong></article>
        <article><span>Interest earned (after fees)</span><strong>{money(data.interest_earned)}</strong></article>
        <article><span>Estimated since last statement</span><strong>+ {money(data.estimated_interest)}</strong></article>
        {till && <article><span>Expected in Lipa na M-Pesa till</span><strong>{money(till.expected)}</strong></article>}
      </div>
      {due.length > 0 && <section className="investReminder" role="status" aria-label="Monthly check due">
        <div>
          <b>Monthly check due for {data.this_month}</b>
          <p>Record the rate {due.map((i) => i.name).join(" and ")} {due.length > 1 ? "pay" : "pays"} now, and the balance if you have the statement,
            so estimates and interest stay right.</p>
        </div>
        {canMove && <button type="button" onClick={() => setPreset({ id: due[0].id, kind: "MONTHLY", nonce: Date.now() })}>
          Do the check{due.length > 1 ? ` for ${due[0].name}` : ""}</button>}
      </section>}
      {adding && <NewInvestmentForm onCancel={() => setAdding(false)} onSaved={async () => { setAdding(false); await load(); }} />}
      {data.investments.length > 0 && <SpareMoney spare={spare} investments={data.investments} canMove={canMove}
        onInvest={(choice) => setPreset({ ...choice, nonce: Date.now() })} />}
      {data.investments.length
        ? <ul className="loanList investList">{data.investments.map((i) => <InvestmentCard key={i.id} investment={i} sessions={data.agency_sessions}
          spare={spare} preset={preset?.id === i.id ? preset : null} month={data.this_month}
          canMove={canMove} canCorrect={can("accounting.reverse_cashentry")} onChanged={async () => { setPreset(null); await load(); }} />)}</ul>
        : <Empty>No investment accounts yet. Add your MMF to start tracking what you put in, take out and earn.</Empty>}
      <InterestCalculator defaultRate={rated ? Number(rated.current_rate.annual_rate) : ""} defaultTax={rated ? Number(rated.tax_rate) : 15}
        rateSource={rated ? `${rated.name}, ${rated.current_rate.label}` : ""} />
    </>
  );
}
