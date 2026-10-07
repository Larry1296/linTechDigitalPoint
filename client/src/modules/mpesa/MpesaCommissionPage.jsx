import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const date = (value) => (value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const today = () => new Date().toLocaleDateString("en-CA");
const monthValue = (value) => String(value || "").slice(0, 7);
const lastMonth = () => { const d = new Date(); d.setDate(0); return d.toLocaleDateString("en-CA").slice(0, 7); };
const monthName = (value) => new Date(`${monthValue(value)}-15T12:00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" });

// What each place does to the agency's money, shown under the choice.
const EFFECT = {
  AGENCY_FLOAT: "the shift's float goes up by this amount.",
  AGENCY_FLOAT_TO_OWNER: "the float goes up and the drawer goes down by this amount, like a withdrawal. The cash is the business's, kept outside the agency.",
  AGENCY_CASH: "the shift's cash goes up by this amount.",
};
const GROUPS = [["During the open shift", (p) => p.startsWith("AGENCY_")], ["Between shifts", (p) => p === "OPENING_FLOAT"],
  ["Outside the agency", (p) => !p.startsWith("AGENCY_") && p !== "OPENING_FLOAT"]];

// Commission Safaricom paid: for which month, how much, when and where the money went (Safaricom gives no M-Pesa code for it).
function RecordForm({ data, onSaved, onCancel }) {
  const [outlet, setOutlet] = useState(String(data.outlets[0]?.id ?? ""));
  const [place, setPlace] = useState("AGENCY_FLOAT");
  const [month, setMonth] = useState(data.due_month ? monthValue(data.due_month) : lastMonth());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const shop = data.outlets.find((o) => String(o.id) === outlet);
  const shifts = shop?.opening_shifts || [];
  const [shift, setShift] = useState("");
  const chosenShift = shifts.find((s) => String(s.id) === shift) || shifts[0];
  const agency = place.startsWith("AGENCY_");
  const opening = place === "OPENING_FLOAT";
  const placeName = Object.fromEntries(data.places)[place];
  const blocked = (agency && !shop?.open_session) || (opening && !chosenShift);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const paidOn = agency ? today() : opening ? String(chosenShift.opened_on) : values.paid_on;
    const later = paidOn.slice(0, 7) > month;
    if (!(await confirmAction({ title: `Record ${money(values.amount)} commission for ${monthName(month)}?`,
      text: `${later ? `It counts as ${monthName(month)}'s income (owed by Safaricom until ${date(paidOn)}). ` : ""}The money went to: ${placeName.toLowerCase()}${opening ? ` (the shift of ${date(paidOn)})` : ""}.`,
      confirmButtonText: "Record commission" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/mpesa/commission/", { method: "POST", body: JSON.stringify({ outlet: Number(outlet), period: `${month}-01`, amount: values.amount,
        settlement_method: place, paid_on: paidOn, notes: values.notes,
        ...(agency && shop?.open_session ? { session_id: shop.open_session } : {}), ...(opening ? { session_id: chosenShift.id } : {}),
        idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="Record commission">
      <h2>Record Safaricom commission</h2>
      <fieldset disabled={busy} className="loanFields">
        {data.outlets.length > 1 && <FormField label="Agency outlet">
          <select value={outlet} onChange={(event) => { setOutlet(event.target.value); setShift(""); }}>
            {data.outlets.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </FormField>}
        <FormField label="Month it was earned" name="month" type="month" required max={today().slice(0, 7)} value={month} onChange={(event) => setMonth(event.target.value)} />
        <FormField label={`Amount Safaricom paid (${businessCurrency()})`} name="amount" type="number" min="0.01" step="0.01" required
          max={opening && chosenShift ? chosenShift.room : undefined} />
        <FormField label="Where the money went">
          <select value={place} onChange={(event) => setPlace(event.target.value)}>
            {GROUPS.map(([label, belongs]) => <optgroup key={label} label={label}>
              {data.places.filter(([value]) => belongs(value)).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
            </optgroup>)}
          </select>
        </FormField>
        {agency && <p className="muted">{shop?.open_session ? `It is recorded in ${shop.name}'s open shift today: ${EFFECT[place]}`
          : `Open ${shop?.name || "the agency"}'s shift first, or choose where else the money went.`}</p>}
        {opening && (shifts.length ? <>
          <FormField label="Shift whose opening float had it">
            <select value={String(chosenShift.id)} onChange={(event) => setShift(event.target.value)}>
              {shifts.map((s) => <option key={s.id} value={s.id}>{date(s.opened_on)}: opened with float {money(s.opening_float)}</option>)}
            </select>
          </FormField>
          <p className="muted">Safaricom paid it after the previous shift closed, so it was already counted in this shift's opening float.
            The float does not change; up to {money(chosenShift.room)} of that shift's opening float can be commission
            {chosenShift.carried_float != null ? ` (it opened with more than the ${money(chosenShift.carried_float)} the shift before closed with)` : ""}.</p>
        </> : <p className="muted">No recent shift opened with more float than the shift before it closed with, so no commission can be in an opening float.</p>)}
        {!agency && !opening && <FormField label="Date it was paid" name="paid_on" type="date" required max={today()} defaultValue={today()} />}
      <FormField label="Note (optional)" name="notes" maxLength={500} autoComplete="off" />
      </fieldset>
      <p className="muted">Commission counts as income in the month it was earned, even when Safaricom pays it the next month. Include the commission on airtime you sold; if Safaricom pays it separately, record it as its own entry with a note such as “Airtime commission”.</p>
      <div className="actionRow">
        <button disabled={busy || blocked}>Record commission</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the commission." message={error} />
    </form>
  );
}

// Each month's commission, the agency's own running costs and what was left, as bars with exact figures beside them.
function MonthlyProfit({ months }) {
  const largest = Math.max(1, ...months.flatMap((m) => [Number(m.commission), Number(m.expenses)]));
  return (
    <div className="trendTable"><table className="commissionMonths">
      <caption>The agency month by month</caption>
      <thead><tr><th scope="col">Month</th><th scope="col">Commission earned</th><th scope="col">Agency running costs</th><th scope="col">Profit or loss</th></tr></thead>
      <tbody>{[...months].reverse().map((m) => (
        <tr key={m.month}>
          <th scope="row">{m.label}</th>
          <td><span className="commissionBar"><i style={{ width: `${(Number(m.commission) / largest) * 100}%` }} /></span>{money(m.commission)}</td>
          <td><span className="commissionBar costs"><i style={{ width: `${(Number(m.expenses) / largest) * 100}%` }} /></span>{money(m.expenses)}</td>
          <td className={Number(m.profit) < 0 ? "negative" : undefined}><strong>{Number(m.profit) < 0 ? `Loss ${money(-m.profit)}` : money(m.profit)}</strong></td>
        </tr>))}</tbody>
    </table></div>
  );
}

export function MpesaCommissionPage() {
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState("");
  const load = async () => {
    try {
      setData(await api("/api/v1/mpesa/commission/"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const canAdd = can("mpesa.add_mpesacommissionentry");
  const undo = async (entry) => {
    const values = await askForm({ title: `Undo ${money(entry.amount)} commission for ${entry.month}?`,
      text: "Its income comes out of the books and the money comes back out of where it was recorded.", confirmButtonText: "Undo",
      fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. wrong amount" }] });
    if (!values) return;
    setNotice("");
    try {
      await api(`/api/v1/mpesa/commission/${entry.id}/undo/`, { method: "POST", body: JSON.stringify({ reason: values.reason }) });
      await load();
    } catch (err) {
      setNotice(err.message);
    }
  };
  return (
    <>
      <div className="loanSummary">
        <h1>Safaricom commission</h1>
        {canAdd && !adding && data.outlets.length > 0 && <button type="button" onClick={() => setAdding(true)}>Record commission</button>}
      </div>
      <p className="muted">What the M-Pesa agency earns. Customers' deposits and withdrawals, and the money for airtime you sell, are not income; the
        agency's income is the commission Safaricom pays each month, including commission on airtime, less the agency's own running costs.</p>
      {data.due_month && <section className="investReminder" role="status" aria-label="Commission due">
        <div><b>{data.due_label}'s commission is not recorded yet</b>
          <p>The agency worked in {data.due_label}. When Safaricom pays it, record it here so that month's profit is right.</p></div>
        {canAdd && !adding && <button type="button" onClick={() => setAdding(true)}>Record it</button>}
      </section>}
      <div className="metrics investMetrics">
        <article><span>Commission, last 12 months</span><strong>{money(data.totals.commission)}</strong></article>
        <article><span>Agency running costs</span><strong>{money(data.totals.expenses)}</strong></article>
        <article><span>Agency profit</span><strong className={Number(data.totals.profit) < 0 ? "negative" : undefined}>{money(data.totals.profit)}</strong></article>
      </div>
      {adding && <RecordForm data={data} onCancel={() => setAdding(false)} onSaved={async () => { setAdding(false); await load(); }} />}
      {data.outlets.length === 0 && <Empty>Add an M-Pesa agency outlet on the Agent desk first.</Empty>}
      <section className="panel"><MonthlyProfit months={data.months} /></section>
      <section className="panel">
        <h2>Commission recorded</h2>
        <FormError title="Could not undo it." message={notice} />
        {data.entries.length ? <div className="trendTable"><table className="loanRepayments">
          <thead><tr><th>Earned in</th><th>Amount</th><th>Paid</th><th>Went to</th><th>Reference</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
          <tbody>{data.entries.map((e) => (
            <tr key={e.id} className={e.reversed_at ? "muted" : undefined}>
              <td>{e.month}{e.notes && <small> · {e.notes}</small>}</td>
              <td>{money(e.amount)}{e.reversed_at && <small> · undone ({e.reverse_reason})</small>}</td>
              <td>{date(e.paid_on)}</td>
              <td>{Object.fromEntries(data.places)[e.settlement_method] || e.settlement_method}</td>
              <td>{e.reference || "—"}</td>
              <td>{!e.reversed_at && can("accounting.reverse_cashentry") && <button type="button" className="secondary" onClick={() => void undo(e)}>Undo</button>}</td>
            </tr>))}</tbody>
        </table></div> : <p className="muted">No commission recorded yet.</p>}
      </section>
    </>
  );
}
