import { useEffect, useRef, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { businessParts } from "../../core/organization/MoneyModeChoice";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { InterestCalculator } from "./InterestCalculator";
import { TextArea } from "../../components/forms/TextBox";

// Each time money goes in or comes out, the owner says whose it is. The business's money comes from (or goes back to)
// one of its places and is still the business's while it is in the investment, so its money and figures stay as they
// are. The owner's own money never touches the business. All the interest is the business's profit.
const OWNER = "OWNER";
const BUSINESS = "BUSINESS";
const PLACES = [["MPESA", "Lipa na M-Pesa till"], ["CASH", "Cash drawer"], ["BANK", "Bank"], ["OTHER", "Other money"]];
const placeName = (key) => (PLACES.find(([value]) => value === key)?.[1] || key).toLowerCase();
const APART = "The M-Pesa agency's cash and float are never used.";
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
        <FormField label="Note (optional)"><TextArea name="notes" maxLength={500} placeholder="e.g. withdraw takes 2 days" /></FormField>
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

// Money put in or taken out, and whose it is: the business's (from or back to one of its places) or the owner's own.
function MoveForm({ investment, kind, preset, onSaved, onCancel }) {
  const { user } = useAuth();
  const parts = businessParts(user?.organization);
  const putIn = kind === "DEPOSIT";
  const [whose, setWhose] = useState(preset?.whose ?? (putIn || Number(investment.shop_value) > 0 ? BUSINESS : OWNER));
  const business = whose === BUSINESS;
  const holds = business ? investment.shop_value : investment.owner_value;
  const [amount, setAmount] = useState(preset?.amount ?? (putIn ? "" : String(Math.max(Number(holds) || 0, 0))));
  const [place, setPlace] = useState("MPESA");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const choose = (next) => {
    setWhose(next);
    if (!putIn) setAmount(String(Math.max(Number(next === BUSINESS ? investment.shop_value : investment.owner_value) || 0, 0)));
  };
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const sum = money(values.amount);
    const title = business
      ? (putIn ? `Move ${sum} of the business's money from the ${placeName(place)} into ${investment.name}?` : `Take ${sum} of the business's money out of ${investment.name} back to the ${placeName(place)}?`)
      : (putIn ? `Add ${sum} of your own money to ${investment.name}?` : `Take ${sum} of your own money out of ${investment.name} to you?`);
    const text = business
      ? `It stays the business's money${putIn ? ", kept in the investment" : ""}: the ${placeName(place)} ${putIn ? "goes down" : "goes up"} by ${sum}, and the business's money, sales and profit stay as they are.`
      : "It is not the business's money, so nothing in the business changes.";
    if (!(await confirmAction({ title, text, confirmButtonText: putIn ? "Record money added" : "Record money taken out" }))) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/accounting/investments/${investment.id}/move/`, { method: "POST",
        body: JSON.stringify({ ...values, kind, source: whose, ...(business ? { place } : {}), idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="loanRepay" onSubmit={(event) => void submit(event)} aria-label={putIn ? "Add money" : "Take money out"}>
      <fieldset disabled={busy} className="loanFields">
        <fieldset className="investWhose">
          <legend>Whose money {putIn ? "is it" : "is coming out"}?</legend>
          <label><input type="radio" name="whose" checked={business} onChange={() => choose(BUSINESS)} /> The business's money
            {!putIn && <small> · {money(investment.shop_value)} in it</small>}</label>
          <label><input type="radio" name="whose" checked={!business} onChange={() => choose(OWNER)} /> My own money
            {!putIn && <small> · {money(investment.owner_value)} in it</small>}</label>
        </fieldset>
        {business && <FormField label={putIn ? "Taken from" : "Put back into"}>
          <select value={place} onChange={(event) => setPlace(event.target.value)}>
            {PLACES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </FormField>}
        {business && parts.length > 1 && <FormField label="Which part's money">
          <select name="unit" defaultValue={parts[0].key}>{parts.map((part) => <option key={part.key} value={part.key}>{part.name}</option>)}</select>
        </FormField>}
        <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" min="0.01" step="0.01"
          max={putIn ? undefined : Math.max(Number(holds) || 0, 0)} value={amount} onChange={(event) => setAmount(event.target.value)} required />
        <p className="muted">{business
          ? `Still the business's money while it is in the investment, so its money and each part's figures stay the same. ${APART}`
          : `Not the business's money: nothing in the business changes. ${APART}`}</p>
        <FormField label={putIn ? "Date the money went in" : "Date the money came out"} name="occurred_on" type="date" max={today()} defaultValue={today()} required />
        {putIn && <p className="muted">Already invested earlier? Choose the day it really went in: interest is worked out from that day.</p>}
        <FormField label="Transaction code or reference (optional)" name="reference" maxLength={120} autoComplete="off" />
        <FormField label="Note (optional)" name="note" maxLength={500} autoComplete="off" />
      </fieldset>
      {!putIn && <p className="muted">Paying a supplier for stock? Record it when you receive the stock: choose
        “Paid the supplier now → from my investment”. The business's money in it pays first, so the withdrawal and the stock it paid for are linked.</p>}
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
      text: difference > 0 ? `${money(difference)} will be recorded as interest earned and added to the business's profit.`
        : difference < 0 ? `${money(-difference)} will be recorded as fees or a loss and taken off the business's profit.` : "This matches the app; nothing will be recorded.",
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
      <p className="muted">The app expects {money(investment.value)}. The difference is the interest (or fees if lower), and it goes into the business's profit.</p>
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
// Each statement next to what the app predicted for the same date, so the estimate can be checked month by month.
function StatementChecks({ investment }) {
  const rows = investment.statements || [];
  if (!rows.length) return null;
  const signed = (value) => (Number(value) < 0 ? `− ${money(-value)}` : `+ ${money(value)}`);
  return (
    <details className="investRates" open>
      <summary>Predicted and actual interest ({rows.length})</summary>
      <table className="loanRepayments">
        <caption>What the app predicted, next to what the statement showed</caption>
        <thead><tr><th scope="col">Statement</th><th scope="col">App predicted</th><th scope="col">Statement showed</th><th scope="col">Difference</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.id}>
            <th scope="row">{date(r.date)}{r.since && <small className="muted"> · since {date(r.since)}</small>}</th>
            <td>{r.predicted == null ? "Not predicted" : signed(r.predicted)}</td>
            <td>{signed(r.actual)}<small className="muted"> · balance {money(r.statement_balance)}</small></td>
            <td>{r.difference == null ? "—" : Math.abs(Number(r.difference)) < 0.5 ? "Same" : signed(r.difference)}</td>
          </tr>))}</tbody>
      </table>
      <p className="muted">Interest after {percent(investment.tax_rate)} tax. A big difference usually means a rate, a date or an amount
        put in or taken out is not recorded as on the statement.</p>
    </details>
  );
}

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

// What each place expects, taken in turn until the owner's own money in the fund is used up: {method: "amount"}.
const fill = (places, room) => places.reduce(([left, chosen], p) => {
  const take = Math.min(Number(p.expected), Math.max(left, 0));
  return [left - take, { ...chosen, [p.method]: take ? String(take) : "" }];
}, [room, {}])[1];

// The business's money already in the fund but recorded as the owner's own: how much from each place. Each place starts
// at what the app expects there, up to what the fund holds as the owner's own.
function BusinessMoneyForm({ investment, places, onSaved, onCancel }) {
  const [amounts, setAmounts] = useState(() => fill(places, Number(investment.owner_value) || 0));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const total = Object.values(amounts).reduce((sum, value) => sum + (Number(value) || 0), 0);
  const key = useRef(crypto.randomUUID());
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: `Record ${money(total)} of ${investment.name} as the business's money?`,
      text: `The till, drawer or bank no longer expects it, the business's money in ${investment.name} goes up by ${money(total)} and your own money in it goes down by the same. The fund's total, sales and profit stay as they are.`,
      confirmButtonText: "Record the business's money" }))) return;
    setBusy(true); setError("");
    try {
      await api(`/api/v1/accounting/investments/${investment.id}/business-money/`, { method: "POST", body: JSON.stringify({
        amounts: Object.fromEntries(Object.entries(amounts).filter(([, value]) => Number(value) > 0)), occurred_on: values.occurred_on, idempotency_key: key.current }) });
      await onSaved();
    } catch (err) { setError(err.message); setBusy(false); }
  };
  return (
    <form className="loanRepay" onSubmit={(event) => void submit(event)} aria-label="The business's money is in here">
      <h4 className="investFormTitle">The business's money is in here</h4>
      <p className="muted">The business's money (what it sold and earned, less what it spent) that you put into {investment.name}. Each place shows
        what the app expects there; keep it, or enter how much of it is in the fund.</p>
      <fieldset disabled={busy} className="loanFields">
        {places.map((p) => <FormField key={p.method} label={`From ${p.label.toLowerCase()} (expects ${money(p.expected)})`} type="number" min="0" step="0.01"
          max={Number(p.expected)} value={amounts[p.method]} onChange={(event) => setAmounts({ ...amounts, [p.method]: event.target.value })} />)}
        <FormField label="Date" name="occurred_on" type="date" max={today()} defaultValue={today()} required />
      </fieldset>
      <p className="muted">Together {money(total)}, out of {money(investment.owner_value)} recorded as your own money in it.</p>
      <div className="actionRow">
        <button disabled={busy || total <= 0}>Record the business's money</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record it." message={error} />
    </form>
  );
}

function InvestmentCard({ investment, funds, places = [], preset, month, canMove, canCorrect, canRemove, onChanged }) {
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
  // Money first recorded as your own that was really the business's: from which place, and how much of it.
  const markBusiness = async (m) => {
    const values = await askForm({ title: `Was this ${money(m.amount)} the business's money?`,
      text: `It came out of the business's place on ${date(m.occurred_on)}: that place goes down by it and the business's money in ${investment.name} goes up. Sales and profit stay as they are.`,
      confirmButtonText: "It was the business's money", fields: [
        { name: "place", label: "It came from", type: "select", value: "MPESA", options: PLACES },
        { name: "amount", label: `How much of it was the business's (${businessCurrency()})`, type: "number", value: String(Number(m.amount)), max: String(Number(m.amount)), required: true },
      ] });
    if (!values) return;
    setError("");
    try {
      await api(`/api/v1/accounting/investments/movements/${m.id}/business/`, { method: "POST", body: JSON.stringify(values) });
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  };
  const undo = async (m) => {
    const values = await askForm({ title: `Undo this ${KIND[m.kind].toLowerCase()} of ${money(m.amount)}?`,
      text: `The investment's value goes back to what it was${m.kind === "INTEREST" || m.kind === "FEE" ? ", and the business's profit with it" : ""}. ${APART}`,
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
        {Number(investment.value) > 0 && <div><dt>Whose it is</dt>
          <dd>Business {money(investment.shop_value)} · Your own {money(investment.owner_value)}</dd></div>}
        <div><dt>Total invested</dt><dd><strong>{money(investment.invested)}</strong> <small>interest is earned on this</small></dd></div>
        <div><dt>Put in</dt><dd>{money(investment.put_in)}</dd></div>
        <div><dt>Taken out</dt><dd>{money(investment.taken_out)}</dd></div>
        <div><dt>Interest earned</dt><dd>{money(investment.interest)}{Number(investment.fees) ? <small> · fees {money(investment.fees)}</small> : null}</dd></div>
        {investment.estimate && <div><dt>Estimated since {date(investment.estimate.since)}</dt>
          <dd>+ {money(investment.estimate.net)} <small>after {percent(investment.tax_rate)} tax</small></dd></div>}
        {investment.estimate && <div><dt>Estimated value today</dt><dd>{money(investment.estimate.value)}</dd></div>}
      </dl>
      <Earning investment={investment} />
      <DayByDay investment={investment} />
      <StatementChecks investment={investment} />
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
              <td>{m.whose === BUSINESS ? (m.kind === "DEPOSIT" || m.kind === "WITHDRAWAL" ? `Business · ${placeName(m.source)}` : "Business")
                : m.source === OWNER ? (m.kind === "DEPOSIT" ? "My own money" : "Me") : "—"}</td>
              <td>{m.reference || m.note || "—"}</td>
              <td>{!m.reversed_at && canCorrect && <div className="actionRow">
                {m.kind === "DEPOSIT" && m.whose !== BUSINESS && !m.purchase && <button type="button" className="secondary" onClick={() => void markBusiness(m)}>It was the business's money</button>}
                <button type="button" className="secondary" onClick={() => void undo(m)}>Undo</button></div>}</td>
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
        ? <MoveForm key={preset?.nonce ?? form} investment={investment} kind={form}
          preset={form === "DEPOSIT" ? preset : null} onCancel={() => setForm(null)} onSaved={done} />
        : form === "STATEMENT"
          ? <StatementForm investment={investment} onCancel={() => setForm(null)} onSaved={done} />
        : form === "BUSINESS"
          ? <BusinessMoneyForm investment={investment} places={places} onCancel={() => setForm(null)} onSaved={done} />
          : canMove && <div className="actionRow">
            {!automatic && <button type="button" className={investment.check_due ? undefined : "secondary"} onClick={() => setForm("MONTHLY")}>Monthly check</button>}
            <button type="button" onClick={() => setForm("DEPOSIT")}>Add money</button>
            <button type="button" className="secondary" disabled={Number(investment.value) <= 0} onClick={() => setForm("WITHDRAWAL")}>Take money out</button>
            <button type="button" className="secondary" onClick={() => setForm("STATEMENT")}>Update from statement</button>
            {places.length > 0 && Number(investment.owner_value) > 0 && <button type="button" className="secondary" onClick={() => setForm("BUSINESS")}>The business's money is in here</button>}
          </div>}
      {!form && canRemove && <div className="actionRow">
        <button type="button" className="linkButton" onClick={() => void removeAll()}>Remove this investment</button>
      </div>}
      <FormError title="Could not do it." message={error} />
    </li>
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
      <p className="muted">Money kept in a money market fund (MMF) or similar so it keeps earning until it is needed, e.g. for stock.
        Each time you put money in or take it out, say whose it is. The business's money stays the business's while it is here, so its
        money, sales and each part's figures do not change; your own money never touches the business. All the interest is the
        business's profit: each statement's balance, less what the app expects (what was put in, less what was taken out, plus
        interest and less fees already recorded).</p>
      <div className="metrics investMetrics">
        {Number(data.total_value) > 0 && <>
          <article><span>The business's money</span><strong>{money(data.shop_value)}</strong>
            <small>Put in from its till, drawer or bank, plus all the interest: still the business's</small></article>
          <article><span>Your own money</span><strong>{money(data.owner_value)}</strong>
            <small>Not the business's: never in its money or figures</small></article>
        </>}
        {data.worth_today != null && Number(data.worth_today) !== Number(data.total_value) &&
          <article><span>Worth today, with interest</span><strong>{money(data.worth_today)}</strong>
            <small>Goes up every day as interest builds</small></article>}
        <article><span>Total invested</span><strong>{money(data.invested)}</strong>
          <small>The business's and yours together; interest is earned on this</small></article>
        <article><span>Recorded value, with interest</span><strong>{money(data.total_value)}</strong></article>
        <article><span>Interest earned (after fees)</span><strong>{money(data.interest_earned)}</strong>
          <small>Added to the business's profit</small></article>
        <article><span>Estimated since last statement</span><strong>+ {money(data.estimated_interest)}</strong></article>
        {earning && Number(earning.year) > 0 && <article><span>Earning now, after tax</span><strong>{money(earning.day)} a day</strong>
          <small>{money(earning.month)} a month · {money(earning.year)} a year</small></article>}
      </div>
      {Number(data.business_in_places) > 0 && Number(data.owner_value) > 0 && <section className="investReminder" role="status" aria-label="Business money not marked">
        <div>
          <b>The app expects {money(data.business_in_places)} of the business's money in its till, drawer or bank</b>
          <p>If that money is really in an investment, press “The business's money is in here” on its card: it fills in what each place
            expects, and records it as the business's money in the fund in one step. Then the business's money here is right and the till,
            drawer and bank are not expected to hold it.</p>
        </div>
      </section>}
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
      {data.investments.length
        ? <ul className="loanList investList">{data.investments.map((i) => <InvestmentCard key={i.id} investment={i} funds={funds} places={data.business_places || []}
          preset={preset?.id === i.id ? preset : null} month={data.this_month}
          canMove={canMove} canCorrect={can("accounting.reverse_cashentry")}
          canRemove={can("accounting.reverse_cashentry") && can("accounting.add_investment")} onChanged={async () => { setPreset(null); await load(); }} />)}</ul>
        : <Empty>No investment accounts yet. Add your MMF to start tracking what you put in, take out and earn.</Empty>}
      <InterestCalculator defaultRate={ratedAt != null ? Number(ratedAt) : ""} defaultTax={rated ? Number(rated.tax_rate) : 15} rateSource={ratedFrom} />
    </>
  );
}
