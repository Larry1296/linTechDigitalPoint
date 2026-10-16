import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { confirmAction } from "../../core/ui/alerts";
import { ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { CashCounter, countPayload, countTotal, emptyCount } from "../mpesa/CashCounter";
import { useLiveRefresh } from "../../core/data/liveRefresh";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const when = (value) => new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

// The difference in words: more, less or exactly what the app expected.
export function differenceText(difference) {
  const value = Number(difference);
  if (Math.abs(value) < 0.005) return "Exactly what the app expected.";
  return value < 0
    ? `${money(-value)} less than the app expected. Something may not have been recorded (a sale at a lower price, money spent, a refund), or money is missing.`
    : `${money(value)} more than the app expected. Something may not have been recorded (a sale, money you added), or starting money is missing.`;
}

function CountForm({ place, onSaved, canAddStarting, onStartingAdded }) {
  const cash = place.method === "CASH";
  const [count, setCount] = useState(emptyCount);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const actual = cash ? countTotal(count) : Number(amount || 0);
  const extra = Math.round((actual - Number(place.expected)) * 100) / 100;
  // More than expected because money was already there before the app was used: record the difference as starting money.
  const addAsStarting = async () => {
    if (!(await confirmAction({ title: `Add ${money(extra)} as money you already had on ${place.label}?`,
      text: "Use this when the money was there before you started recording in the app (money you put in yourself). It is not a sale and does not count as profit.",
      confirmButtonText: "Add as money I already had" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/accounting/money-check/starting/", { method: "POST", body: JSON.stringify({ method: place.method, unit: place.unit, amount: extra.toFixed(2),
        note: "Money already there before using the app", idempotency_key: crypto.randomUUID() }) });
      await onStartingAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const saved = await api("/api/v1/accounting/money-check/", { method: "POST", body: JSON.stringify({
        method: place.method, unit: place.unit, note, ...(cash ? { actual: actual.toFixed(2), cash_count: countPayload(count) } : { actual: amount }) }) });
      setCount(emptyCount());
      setAmount("");
      setNote("");
      await onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="moneyCount" onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy}>
        {cash ? <CashCounter count={count} onChange={setCount} legend={`Count the cash in the ${place.unit ? place.label.toLowerCase() : "drawer"}`} />
          : <FormField label={`Amount you have on ${place.label} (${businessCurrency()})`} type="number" min="0" step="0.01" required
            value={amount} onChange={(event) => setAmount(event.target.value)} />}
        {(cash || amount !== "") && <p className="moneyCompare">You have <b>{money(actual)}</b> · the app expects <b>{money(place.expected)}</b> · {differenceText(actual - Number(place.expected))}</p>}
        {canAddStarting && extra > 0 && (cash || amount !== "") && <div className="formNotice formNoticeInfo">
          <p>Was this money already there before you started using the app, or money you put in yourself? Record it as money you already had,
            then save the count.</p>
          <button type="button" className="secondary" onClick={() => void addAsStarting()}>Add {money(extra)} as money I already had</button>
        </div>}
        <FormField label="Note (optional)" value={note} onChange={(event) => setNote(event.target.value)} maxLength={300} placeholder="e.g. evening count" />
        <button>Save this count</button>
      </fieldset>
      <FormError title="Could not save the count." message={error} />
    </form>
  );
}

// Whose money is in a place: what each part of the business brought in less what it paid out from there.
export function WhoseMoney({ place }) {
  const rows = (place.by_part || []).filter((row) => Number(row.amount) !== 0);
  if (place.unit || rows.length < 2) return null;
  return <table className="moneyParts"><caption>Whose money it is</caption><tbody>
    {rows.map((row) => <tr key={row.unit}><th scope="row">{row.label}</th><td>{Number(row.amount) < 0 ? `− ${money(-Number(row.amount))}` : money(row.amount)}</td></tr>)}
  </tbody></table>;
}

function StartingMoney({ places, onSaved }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open) return <button type="button" className="secondary" onClick={() => setOpen(true)}>Add money I already had</button>;
  const submit = async (event) => {
    event.preventDefault();
    const { place: where, ...values } = Object.fromEntries(new FormData(event.currentTarget));
    const [method, unit] = where.split(":");
    Object.assign(values, { method, unit: unit || null });
    if (!(await confirmAction({ title: `Add ${money(values.amount)} as starting money?`,
      text: "Use this for money you had before you started recording in the app. It is not a sale and does not count as profit.",
      confirmButtonText: "Add starting money" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/accounting/money-check/starting/", { method: "POST", body: JSON.stringify({ ...values, idempotency_key: crypto.randomUUID() }) });
      setOpen(false);
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)}>
      <h3>Money you already had</h3>
      <p className="muted">For example the shop's cash in the drawer, or what was already on the Lipa na M-Pesa till, on the day you started
        using the app, or money you put in yourself. Not M-Pesa agency money.</p>
      <fieldset disabled={busy}>
        <FormField label="Where is it kept?">
          <select name="place" defaultValue={places[0]?.key || "CASH"}>{[...places.map((p) => [p.key, p.label]), ...[["BANK", "Bank"], ["OTHER", "Other"]].filter(([m]) => !places.some((p) => p.method === m))]
            .map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </FormField>
        <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" min="0.01" step="0.01" required />
        <FormField label="Note" name="note" maxLength={160} defaultValue="Starting money" />
        <div className="actionRow"><button>Add starting money</button><button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button></div>
      </fieldset>
      <FormError title="Could not add the starting money." message={error} />
    </form>
  );
}

export function MoneyCheckPage() {
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const load = async () => {
    try {
      setData(await api("/api/v1/accounting/money-check/"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  return (
    <>
      <h1>Money check</h1>
      <p className="muted">For each place you keep money, the app works out what should be there: the money you started with, plus what customers paid,
        minus what you spent, paid suppliers or lent. Count what you really have and compare. If they differ, find what was not recorded,
        for example with a <Link to="/admin/stock-check">stock check</Link>.</p>
      <p className="formNotice formNoticeInfo">{data.mode === "SEPARATE_CASH"
        ? "Each part of the business keeps its own cash drawer, counted on its own. The Lipa na M-Pesa till and the bank are shared; each shows how much of it belongs to each part."
        : "All your cash is in one drawer. Each place shows how much of it each part of the business brought in."}{" "}
        M-Pesa commission paid out to you is your money and is counted here. The M-Pesa agency's cash and float are your business's stock for the agency, like goods on the shelves: they are counted on the <Link to="/admin/mpesa">M-Pesa desk</Link> when you close a shift.</p>
      {result && <p className={Math.abs(Number(result.difference)) < 0.005 ? "formNotice formNoticeSuccess" : "formNotice formNoticeInfo"} role="status">
        Saved. You have {money(result.actual)}; the app expected {money(result.expected)}. {differenceText(result.difference)}</p>}
      <div className="moneyPlaces">{data.places.map((place) => (
        <section key={place.key} className="moneyPlace" aria-labelledby={`place-${place.key}`}>
          <h2 id={`place-${place.key}`}>{place.label}</h2>
          <p className="moneyExpected"><span>The app expects</span><strong>{money(place.expected)}</strong></p>
          <table className="moneyParts"><caption>How it is worked out</caption><tbody>
            {place.parts.map((part) => <tr key={part.key}><th scope="row">{part.label}</th><td>{Number(part.amount) < 0 ? `− ${money(-Number(part.amount))}` : `+ ${money(part.amount)}`}</td></tr>)}
            <tr className="reportTotal"><th scope="row">Expected</th><td>{money(place.expected)}</td></tr>
          </tbody></table>
          <WhoseMoney place={place} />
          {place.last_check && <p className="muted">Last counted {when(place.last_check.created_at)}: {money(place.last_check.actual)} ({differenceText(place.last_check.difference)})</p>}
          {place.counted_at_shift ? <p className="muted">Kept together with the M-Pesa agency's money, so it is counted when the M-Pesa shift opens and
            closes, with the agency's.{" "}<a href="/admin/mpesa">Go to the M-Pesa desk</a></p>
          : can("accounting.add_moneycheck") && <CountForm place={place} onSaved={async (saved) => { setResult(saved); await load(); }}
            canAddStarting={can("accounting.add_cashentry")} onStartingAdded={load} />}
        </section>
      ))}</div>
      {can("accounting.add_cashentry") && <StartingMoney places={data.places} onSaved={load} />}
      {data.history.length > 0 && <section aria-labelledby="history-heading">
        <h2 id="history-heading">Earlier counts</h2>
        <div className="trendTable"><table><thead><tr><th scope="col">When</th><th scope="col">Where</th><th scope="col">You had</th><th scope="col">App expected</th><th scope="col">Difference</th><th scope="col">Counted by</th><th scope="col">Note</th></tr></thead>
          <tbody>{data.history.map((check) => <tr key={check.id}><td>{when(check.created_at)}</td><td>{data.places.find((p) => p.method === check.method && (p.unit || null) === (check.unit || null))?.label || check.method}</td>
            <td>{money(check.actual)}</td><td>{money(check.expected)}</td>
            <td className={Math.abs(Number(check.difference)) < 0.005 ? undefined : "lossText"}>{Math.abs(Number(check.difference)) < 0.005 ? "✓ matched" : Number(check.difference) < 0 ? `${money(-Number(check.difference))} short` : `${money(check.difference)} over`}</td>
            <td>{check.counted_by}</td><td>{check.note}</td></tr>)}</tbody>
        </table></div>
      </section>}
    </>
  );
}
