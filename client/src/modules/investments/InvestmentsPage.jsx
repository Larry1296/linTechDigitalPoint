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

const BUSINESS = [["MPESA", "Lipa na M-Pesa (till)"], ["CASH", "Cash"], ["BANK", "Bank"], ["OTHER", "Other"]];
const AGENCY = [["AGENCY_CASH", "M-Pesa agency cash"], ["AGENCY_FLOAT", "M-Pesa agency float"]];
// The owner's own money from outside the business: any amount can go in, and no till, drawer or bank changes.
const OWNER = ["OWNER", "My own money (from outside the business)"];
const sourceName = (value) => Object.fromEntries([...BUSINESS, ...AGENCY, OWNER])[value] || value;
const KIND = { DEPOSIT: "Put in", WITHDRAWAL: "Taken out", INTEREST: "Interest", FEE: "Fees or loss" };
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const date = (value) => (value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const today = () => new Date().toLocaleDateString("en-CA");
const percent = (value) => `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })}%`;

// The fund an account's name points to, as the server guesses it: "CIC MMF" follows CIC's shilling money market fund,
// "KCB MMF" KCB's; a dollar, equity or other fund of the same manager follows none.
const NOT_THE_MMF = ["dollar", "usd", "equity", "fixed", "balanced", "wealth", "global", "bond"];
export const guessFund = (name, funds) => {
  const words = String(name || "").toLowerCase().replace(/-/g, " ").split(/\s+/);
  if (words.some((w) => NOT_THE_MMF.includes(w))) return "";
  return funds.find((f) => String(f.short || "").toLowerCase().split(/\s+/).every((w) => words.includes(w)))?.code || "";
};
const rateOf = (investment) => investment.earning?.annual_rate ?? investment.fund?.annual_rate ?? investment.current_rate?.annual_rate;

// How risky the kind of investment is: a money market fund is low risk, shares high.
function Risk({ kind }) {
  if (!kind) return null;
  return (
    <p className="investRisk">
      <span className={`investRiskBadge risk${kind.risk ?? 0}`}>{kind.risk_label} risk{kind.risk ? ` · ${kind.risk} of 5` : ""}</span>
      {" "}{kind.label}: {kind.risk_note}
    </p>
  );
}

// Where the money goes: a fund the app follows (its rate comes in by itself) or another account whose rate is typed in.
function NewInvestmentForm({ funds, kinds, thenAdd, onSaved, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [fund, setFund] = useState(null); // null until chosen: follows the name
  const [kind, setKind] = useState("MMF");
  const chosen = fund ?? guessFund(name, funds);
  const followed = funds.find((f) => f.code === chosen);
  const risk = followed ? followed.kind : kinds.find((k) => k.code === kind);
  const pick = (code) => {
    setFund(code);
    const picked = funds.find((f) => f.code === code);
    if (picked && (!name || funds.some((f) => name === `${f.short} MMF`))) setName(`${picked.short} MMF`);
  };
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const values = Object.fromEntries(new FormData(event.currentTarget));
      const row = await api("/api/v1/accounting/investments/", { method: "POST",
        body: JSON.stringify({ ...values, fund: chosen, kind: chosen ? "MMF" : kind, annual_rate: chosen ? null : values.annual_rate || null }) });
      await onSaved(row);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="New investment">
      <h2>{thenAdd ? "Add money to a new investment" : "Add an investment account"}</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Where are you investing?">
          <select value={chosen} onChange={(event) => pick(event.target.value)}>
            {funds.map((f) => <option key={f.code} value={f.code}>
              {f.name}{f.annual_rate != null ? ` · ${percent(f.annual_rate)} a year now` : ""}</option>)}
            <option value="">Another fund, Sacco, bank or account (I'll enter the rate)</option>
          </select>
        </FormField>
        <FormField label="Name of the fund or account" name="name" required minLength={2} maxLength={120} placeholder="e.g. CIC MMF"
          autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} />
        {!chosen && <FormField label="What kind is it?">
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            {kinds.map((k) => <option key={k.code} value={k.code}>{k.label}</option>)}
          </select>
        </FormField>}
        <FormField label="Account number (optional)" name="account_number" maxLength={60} autoComplete="off" />
        {!chosen && <FormField label="Yearly interest rate it pays now (%)" name="annual_rate" type="number" min="0" max="100" step="0.001"
          placeholder="e.g. 13.25 — the annual yield in the fund's app or SMS" />}
        <FormField label="Withholding tax on interest (%)" name="tax_rate" type="number" min="0" max="100" step="0.01" defaultValue="15" required />
        <FormField label="Note (optional)"><textarea name="notes" maxLength={500} placeholder="e.g. spare agency cash, withdraw takes 2 days" /></FormField>
      </fieldset>
      <Risk kind={risk} />
      {followed && <p className="muted">The app reads {followed.short}'s rate on its own website{followed.annual_rate == null ? " now" : ""} and checks it
        again every 10 days, so interest estimates stay right without a monthly check. You still record the balance from your statement now and then.</p>}
      <div className="actionRow">
        <button disabled={busy}>{thenAdd ? "Next: the amount" : "Add account"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not add the account." message={error} />
    </form>
  );
}

// "Add money": into an investment already held, or a new one.
function AddMoneyChooser({ investments, onPick, onNew, onCancel }) {
  const [target, setTarget] = useState(investments[0] ? String(investments[0].id) : "new");
  const submit = (event) => {
    event.preventDefault();
    if (target === "new") onNew();
    else onPick(Number(target));
  };
  return (
    <form className="formCard investChooser" onSubmit={submit} aria-label="Add money to">
      <h2>Add money to</h2>
      <fieldset className="loanFields">
        <legend className="visuallyHidden">Add money to</legend>
        {investments.map((i) => (
          <label key={i.id} className="investChoice">
            <input type="radio" name="target" value={String(i.id)} checked={target === String(i.id)} onChange={() => setTarget(String(i.id))} />
            <span><b>{i.name}</b> · {money(i.estimate?.value ?? i.value)} now
              {rateOf(i) != null && ` · ${percent(rateOf(i))} a year`}{i.kind && ` · ${i.kind.risk_label.toLowerCase()} risk`}</span>
          </label>))}
        <label className="investChoice">
          <input type="radio" name="target" value="new" checked={target === "new"} onChange={() => setTarget("new")} />
          <span><b>A new investment</b> · CIC, KCB, Old Mutual and others, or another account</span>
        </label>
      </fieldset>
      <div className="actionRow">
        <button>Continue</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
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
  const own = source === OWNER[0];
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const where = sourceName(values.source).toLowerCase();
    const text = own
      ? (putIn ? "It is your own money put into the business. Your cash, till and bank do not change, and profit does not change."
        : "It goes to you, out of the business. Your cash, till and bank do not change, and profit does not change.")
      : putIn ? `It comes out of your ${where}. It is still your money, so profit does not change.` : `It goes back into your ${where}.`;
    const added = Number(investment.value) > 0 ? ` It is added to the ${money(investment.value)} already in it.` : "";
    if (!(await confirmAction({ title: putIn ? `Add ${money(values.amount)} to ${investment.name}?` : `Take ${money(values.amount)} out of ${investment.name}?`,
      text: putIn ? `${text}${added}` : text,
      confirmButtonText: putIn ? "Record money added" : "Record money taken out" }))) return;
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
    <form className="loanRepay" onSubmit={(event) => void submit(event)} aria-label={putIn ? "Add money" : "Take money out"}>
      <fieldset disabled={busy} className="loanFields">
        <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" min="0.01" step="0.01"
          max={putIn ? undefined : investment.value} value={amount} onChange={(event) => setAmount(event.target.value)} required />
        <FormField label={putIn ? "Taken from" : "Paid to"}>
          <select name="source" value={source} onChange={(event) => setSource(event.target.value)}>
            {BUSINESS.map(([value, label]) => <option key={value} value={value}>
              {label}{putIn && available(value) != null ? ` · ${money(available(value))} expected` : ""}</option>)}
            {sessions.length > 0 && AGENCY.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            <option value={OWNER[0]}>{putIn ? OWNER[1] : "Me, the owner (out of the business)"}</option>
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
        <button disabled={busy}>{putIn ? "Record money added" : "Record money taken out"}</button>
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

// What the money earns now at today's rate, after withholding tax.
function Earning({ investment }) {
  const e = investment.earning;
  if (!e) return null;
  const tile = (label, period) => (
    <div><dt>{label}</dt><dd><strong>{money(e[period].net)}</strong>
      <small>{money(e[period].gross)} before {percent(investment.tax_rate)} tax</small></dd></div>
  );
  return (
    <section className="investEarning" aria-label={`What ${investment.name} earns`}>
      <p>At {percent(e.annual_rate)} a year, {money(e.balance)}{e.estimated_balance ? " (estimated value today)" : ""} earns after tax:</p>
      <dl className="investEarningTiles">
        {tile("A day", "day")}
        {tile("A month", "month")}
        {tile("A year", "year")}
      </dl>
      <p className="muted">A year counts each month's interest earning interest once it is added. The fund's rate changes, so these are a guide.</p>
    </section>
  );
}

// Every day from the first money put in, newest first: what is invested, what the day's interest added and the total after it.
function DayByDay({ investment }) {
  const days = investment.daily || [];
  if (!days.length) return null;
  const moved = (d) => Number(d.moved) > 0 ? <small> · + {money(d.moved)} put in</small>
    : Number(d.moved) < 0 ? <small> · − {money(-d.moved)} taken out</small> : null;
  return (
    <details className="investDaily">
      <summary>Day by day since {date(days[days.length - 1].date)}: {money(days[0].invested)} invested, worth {money(days[0].value)} today</summary>
      <table className="loanRepayments">
        <caption className="visuallyHidden">{investment.name} day by day</caption>
        <thead><tr><th>Date</th><th>Invested</th><th>Interest that day</th><th>Interest so far</th><th>Total</th></tr></thead>
        <tbody>{days.map((d) => (
          <tr key={d.date}>
            <td>{date(d.date)}</td>
            <td>{money(d.invested)}{moved(d)}</td>
            <td>{Number(d.interest) < 0 ? `− ${money(-d.interest)}` : `+ ${money(d.interest)}`}{d.statement && <small> · from statement</small>}</td>
            <td>{money(d.interest_so_far)}</td>
            <td><strong>{money(d.value)}</strong></td>
          </tr>))}</tbody>
      </table>
      <p className="muted">Interest is worked out each day on what is in the fund that day, at the fund's rate for that day, and added
        at each month end after {percent(investment.tax_rate)} tax. It is an estimate until a statement confirms it.</p>
    </details>
  );
}

// Where the rate comes from: the fund's published rate, kept up to date by the app, or typed in each month.
function RateSource({ investment, funds, canMove, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const fund = investment.fund;
  const follow = async (code) => {
    const name = funds.find((f) => f.code === code)?.name;
    if (!(await confirmAction({ title: code ? `Follow ${name}'s published rate?` : "Enter the rate yourself?",
      text: code ? "The app reads the rate on the fund's website and checks it again every 10 days. Estimates use each rate from its date."
        : "The app stops updating the rate; record it with the monthly check.",
      confirmButtonText: code ? "Follow the fund's rate" : "Enter it myself" }))) return;
    setBusy(true);
    try {
      await api(`/api/v1/accounting/investments/${investment.id}/fund/`, { method: "POST", body: JSON.stringify({ fund: code }) });
      await onChanged();
    } catch (err) {
      setNote(err.message);
    } finally {
      setBusy(false);
    }
  };
  const checkNow = async () => {
    setBusy(true);
    setNote("");
    try {
      const result = await api(`/api/v1/accounting/investments/funds/${fund.code}/check/`, { method: "POST" });
      if (!result.started) {
        await onChanged();
        return;
      }
      // The check takes a minute or two; the page picks the rate up then.
      setNote(`Checking ${fund.short}'s current rate. It shows here in a minute or two.`);
      [90, 180].forEach((seconds) => setTimeout(() => void onChanged(), seconds * 1000));
    } catch (err) {
      setNote(err.message);
    } finally {
      setBusy(false);
    }
  };
  const suggested = !fund && guessFund(investment.name, funds);
  return (
    <div className="investSource">
      {fund
        ? <p>{fund.annual_rate != null
          ? <>Rate: <strong>{fund.short}'s published rate</strong>, {percent(fund.annual_rate)} a year
            {fund.effective_annual_rate != null && <> ({percent(fund.effective_annual_rate)} with monthly interest added)</>}, as of {date(fund.as_of)}.
            {" "}Checked {date(fund.checked_on)}; next check by {date(fund.next_check_on)}.</>
          : <>Rate: follows <strong>{fund.name}</strong>. The app is getting its current rate.</>}</p>
        : <p>Rate: entered by hand with the monthly check.</p>}
      {canMove && <div className="actionRow">
        {fund?.can_check_now && <button type="button" className="secondary" disabled={busy} onClick={() => void checkNow()}>
          {busy ? "Checking…" : `Check ${fund.short}'s rate now`}</button>}
        {fund
          ? <button type="button" className="linkButton" disabled={busy} onClick={() => void follow("")}>Enter the rate myself instead</button>
          : funds.map((f) => <button key={f.code} type="button" className={f.code === suggested ? "secondary" : "linkButton"} disabled={busy}
            onClick={() => void follow(f.code)}>Follow {f.name}'s published rate</button>)}
      </div>}
      {note && <p className="muted" role="status">{note}</p>}
    </div>
  );
}

function InvestmentCard({ investment, funds, sessions, spare, preset, month, canMove, canCorrect, canRemove, onChanged }) {
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
  const published = investment.fund?.annual_rate != null ? investment.fund : null;
  // An account following a fund's current rate needs no monthly rate check; its balance is still updated from statements.
  const automatic = Boolean(investment.fund?.fresh);
  // An account recorded by mistake: everything in it is undone, so each amount goes back where it came from.
  const removeAll = async () => {
    const values = await askForm({ title: `Remove ${investment.name}?`,
      text: Number(investment.value) > 0 || investment.movements.some((m) => !m.reversed_at)
        ? `Everything recorded in it is undone: ${money(investment.value)} goes back where it came from and it no longer shows here.`
        : "It no longer shows here.",
      confirmButtonText: "Remove", fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. added by mistake" }] });
    if (!values) return;
    setError("");
    try {
      await api(`/api/v1/accounting/investments/${investment.id}/remove/`, { method: "POST", body: JSON.stringify({ reason: values.reason }) });
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  };
  const undo = async (m) => {
    const values = await askForm({ title: `Undo this ${KIND[m.kind].toLowerCase()} of ${money(m.amount)}?`,
      text: m.source === OWNER[0] ? "It was your own money, so your cash, till and bank do not change."
        : m.source ? `The money goes back to your ${sourceName(m.source).toLowerCase()}.` : "The investment's value goes back to what it was.",
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
        {published
          ? <span className="loanStatus investRate" title={`As of ${date(published.as_of)}, checked ${date(published.checked_on)}`}>
            {percent(published.annual_rate)} a year · {published.short} rate, automatic</span>
          : rate
            ? <span className="loanStatus investRate" title={`Recorded ${date(rate.recorded_on)}`}>{percent(rate.annual_rate)} a year · {rate.label}</span>
            : <span className="loanStatus overdue">No rate recorded</span>}
      </header>
      <Risk kind={investment.kind} />
      <dl className="loanFigures">
        <div><dt>Recorded value</dt><dd><strong>{money(investment.value)}</strong></dd></div>
        <div><dt>Put in</dt><dd>{money(investment.put_in)}</dd></div>
        <div><dt>Taken out</dt><dd>{money(investment.taken_out)}</dd></div>
        <div><dt>Interest earned</dt><dd>{money(investment.interest)}{Number(investment.fees) ? <small> · fees {money(investment.fees)}</small> : null}</dd></div>
        {investment.estimate && <div><dt>Estimated since {date(investment.estimate.since)}</dt>
          <dd>+ {money(investment.estimate.net)} <small>after {percent(investment.tax_rate)} tax</small></dd></div>}
        {investment.estimate && <div><dt>Estimated value today</dt><dd>{money(investment.estimate.value)}</dd></div>}
      </dl>
      <Earning investment={investment} />
      <DayByDay investment={investment} />
      <RateSource investment={investment} funds={funds} canMove={canMove} onChanged={onChanged} />
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
              <tr key={r.month}><td>{r.label}</td><td>{percent(r.annual_rate)}{r.automatic && <small> · automatic</small>}</td><td>{r.statement_balance != null ? money(r.statement_balance) : "—"}</td>
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
            {!automatic && <button type="button" className={investment.check_due ? undefined : "secondary"} onClick={() => setForm("MONTHLY")}>Monthly check</button>}
            <button type="button" onClick={() => setForm("DEPOSIT")}>Add money</button>
            <button type="button" className="secondary" disabled={Number(investment.value) <= 0} onClick={() => setForm("WITHDRAWAL")}>Take money out</button>
            <button type="button" className="secondary" onClick={() => setForm("STATEMENT")}>Update from statement</button>
          </div>}
      {!form && canRemove && <div className="actionRow">
        <button type="button" className="linkButton" onClick={() => void removeAll()}>Remove this investment</button>
      </div>}
      <FormError title="Could not do it." message={error} />
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
  const [adding, setAdding] = useState(false); // true, or "deposit" when money goes in once it is added
  const [choosing, setChoosing] = useState(false);
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
  const rated = data.investments.find((i) => i.earning) || data.investments.find((i) => i.current_rate);
  const ratedAt = rated?.earning ? rated.earning.annual_rate : rated?.current_rate?.annual_rate;
  const ratedFrom = rated ? (rated.fund?.annual_rate != null ? `${rated.fund.short}'s published rate as of ${date(rated.fund.as_of)}` : `${rated.name}, ${rated.current_rate?.label}`) : "";
  const funds = data.funds || [];
  const earning = data.earning;
  return (
    <>
      <div className="loanSummary">
        <h1>Investments</h1>
        {!adding && !choosing && <div className="actionRow">
          {canMove && <button type="button" onClick={() => setChoosing(true)}>Add money</button>}
          {can("accounting.add_investment") && <button type="button" className="secondary" onClick={() => setAdding(true)}>Add investment account</button>}
        </div>}
      </div>
      <p className="muted">Spare money kept in a money market fund (MMF) or similar. Putting money in or taking it out is still your money,
        so profit does not change; only the interest it earns is income.</p>
      <div className="metrics investMetrics">
        {data.worth_today != null && Number(data.worth_today) !== Number(data.total_value) &&
          <article><span>Worth today, with interest</span><strong>{money(data.worth_today)}</strong>
            <small>Goes up every day as interest builds</small></article>}
        <article><span>Invested now</span><strong>{money(data.total_value)}</strong></article>
        <article><span>Interest earned (after fees)</span><strong>{money(data.interest_earned)}</strong></article>
        <article><span>Estimated since last statement</span><strong>+ {money(data.estimated_interest)}</strong></article>
        {earning && Number(earning.year) > 0 && <article><span>Earning now, after tax</span><strong>{money(earning.day)} a day</strong>
          <small>{money(earning.month)} a month · {money(earning.year)} a year</small></article>}
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
      {choosing && <AddMoneyChooser investments={data.investments} onCancel={() => setChoosing(false)}
        onPick={(id) => { setChoosing(false); setPreset({ id, kind: "DEPOSIT", nonce: Date.now() }); }}
        onNew={() => { setChoosing(false); setAdding("deposit"); }} />}
      {adding && <NewInvestmentForm funds={funds} kinds={data.kinds || []} thenAdd={adding === "deposit"} onCancel={() => setAdding(false)}
        onSaved={async (row) => {
          const deposit = adding === "deposit";
          setAdding(false);
          await load();
          if (deposit && row?.id) setPreset({ id: row.id, kind: "DEPOSIT", nonce: Date.now() });
        }} />}
      {data.investments.length > 0 && <SpareMoney spare={spare} investments={data.investments} canMove={canMove}
        onInvest={(choice) => setPreset({ ...choice, nonce: Date.now() })} />}
      {data.investments.length
        ? <ul className="loanList investList">{data.investments.map((i) => <InvestmentCard key={i.id} investment={i} funds={funds} sessions={data.agency_sessions}
          spare={spare} preset={preset?.id === i.id ? preset : null} month={data.this_month}
          canMove={canMove} canCorrect={can("accounting.reverse_cashentry")}
          canRemove={can("accounting.reverse_cashentry") && can("accounting.add_investment")} onChanged={async () => { setPreset(null); await load(); }} />)}</ul>
        : <Empty>No investment accounts yet. Add your MMF to start tracking what you put in, take out and earn.</Empty>}
      <InterestCalculator defaultRate={ratedAt != null ? Number(ratedAt) : ""} defaultTax={rated ? Number(rated.tax_rate) : 15} rateSource={ratedFrom} />
    </>
  );
}
