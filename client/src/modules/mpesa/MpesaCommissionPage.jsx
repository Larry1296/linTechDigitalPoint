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
const UNITS = [["MPESA", "M-Pesa agency"], ["SHOP", "Shop"], ["CYBER", "Services"]];
const blankCost = () => ({ id: crypto.randomUUID(), category: "", description: "", amount: "", unit: "MPESA" });

// Safaricom's payment next to what the app worked out for that month from your readings.
function Comparison({ estimate, amount }) {
  if (!estimate) return null;
  const paid = Number(amount) || 0;
  const expected = Number(estimate.expected);
  const gap = paid - expected;
  return (
    <div className="commissionCompare" role="status">
      <span>The app worked out <b>{money(expected)}</b> for {estimate.label}{estimate.current ? " (forecast to the month's end)" : ""}
        {estimate.unknown > 0 ? `, with ${estimate.unknown} transactions not worked out yet` : ""}.</span>
      {paid > 0 && <span>{Math.abs(gap) < 0.5 ? "Safaricom paid the same."
        : `Safaricom paid ${money(Math.abs(gap))} ${gap > 0 ? "more" : "less"} (${expected ? Math.round((gap / expected) * 100) : 0}%).`}
        {Math.abs(gap) >= 0.5 && Math.abs(gap) > expected * 0.1 ? " A big difference: check the readings, or Safaricom's statement for that month." : ""}</span>}
    </div>
  );
}

// Any part of the commission spent straight away: what on, how much, for which part of the business. Each is a cost.
function SpentLines({ lines, onChange, categories }) {
  const set = (id, key, value) => onChange(lines.map((line) => (line.id === id ? { ...line, [key]: value } : line)));
  return (
    <fieldset className="commissionSpent">
      <legend>Spent straight from the commission (optional)</legend>
      <p className="muted">Money from this commission you used outside the system, such as rent or wages. Each one is recorded as money
        spent, so profit is right; the rest goes where you chose above.</p>
      <datalist id="commission-cost-types">{categories.map((c) => <option key={c.id} value={c.name} />)}</datalist>
      {lines.map((line, index) => (
        <div key={line.id} className="commissionSpentLine">
          <FormField label="Type of cost" list="commission-cost-types" required maxLength={120} placeholder="Rent, wages, transport…"
            value={line.category} onChange={(event) => set(line.id, "category", event.target.value)} />
          <FormField label="What for" required maxLength={500} placeholder="e.g. October shop rent" value={line.description}
            onChange={(event) => set(line.id, "description", event.target.value)} />
          <FormField label={`Amount (${businessCurrency()})`} type="number" min="0.01" step="0.01" required value={line.amount}
            onChange={(event) => set(line.id, "amount", event.target.value)} />
          <FormField label="For">
            <select value={line.unit} onChange={(event) => set(line.id, "unit", event.target.value)}>
              {UNITS.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
            </select>
          </FormField>
          <button type="button" className="secondary" aria-label={`Remove cost ${index + 1}`} onClick={() => onChange(lines.filter((l) => l.id !== line.id))}>Remove</button>
        </div>
      ))}
      <button type="button" className="secondary" onClick={() => onChange([...lines, blankCost()])}>+ Add something it was spent on</button>
    </fieldset>
  );
}

function RecordForm({ data, onSaved, onCancel, canSpend }) {
  const [outlet, setOutlet] = useState(String(data.outlets[0]?.id ?? ""));
  const [amount, setAmount] = useState("");
  const [costs, setCosts] = useState([]);
  const [categories, setCategories] = useState([]);
  useEffect(() => {
    if (!canSpend) return;
    api("/api/v1/accounting/categories/").then((rows) => setCategories(Array.isArray(rows) ? rows : rows.results || [])).catch(() => {});
  }, [canSpend]);
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
  const spent = costs.reduce((sum, line) => sum + (Number(line.amount) || 0), 0);
  const kept = (Number(amount) || 0) - spent;
  const estimate = (data.estimates || []).find((row) => monthValue(row.month) === month);
  const allSpent = spent > 0 && kept === 0;  // nothing left to put anywhere
  const blocked = (agency && !shop?.open_session && !allSpent) || (opening && !chosenShift && !allSpent) || kept < 0;
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const paidOn = agency ? today() : opening ? String(chosenShift.opened_on) : values.paid_on;
    const later = paidOn.slice(0, 7) > month;
    const where = kept > 0 ? `${spent ? `${money(kept)} went to` : "The money went to"}: ${placeName.toLowerCase()}${opening ? ` (the shift of ${date(paidOn)})` : ""}.` : "";
    if (!(await confirmAction({ title: `Record ${money(values.amount)} commission for ${monthName(month)}?`,
      text: `${later ? `It counts as ${monthName(month)}'s income (owed by Safaricom until ${date(paidOn)}). ` : ""}${spent ? `${money(spent)} was spent on ${costs.map((c) => c.description || c.category).join(", ")}, recorded as money spent. ` : ""}${where}`,
      confirmButtonText: "Record commission" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/mpesa/commission/", { method: "POST", body: JSON.stringify({ outlet: Number(outlet), period: `${month}-01`, amount: values.amount,
        settlement_method: place, paid_on: paidOn, notes: values.notes,
        ...(agency && shop?.open_session ? { session_id: shop.open_session } : {}), ...(opening ? { session_id: chosenShift.id } : {}),
        ...(costs.length ? { spent: costs.map(({ category, description, amount: value, unit }) => ({ category, description, amount: value, unit })) } : {}),
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
          max={opening && chosenShift && !spent ? chosenShift.room : undefined} value={amount} onChange={(event) => setAmount(event.target.value)} />
        <Comparison estimate={estimate} amount={amount} />
        <FormField label={spent ? "Where the rest went" : "Where the money went"}>
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
      {canSpend && <SpentLines lines={costs} onChange={setCosts} categories={categories} />}
      {spent > 0 && <p className={kept < 0 ? "formNotice formNoticeError" : "muted"} role="status">{kept < 0
        ? `That is ${money(-kept)} more than Safaricom paid.`
        : `${money(spent)} spent, ${money(kept)} ${kept > 0 ? `goes to: ${placeName.toLowerCase()}` : "left"}. All ${money(Number(amount) || 0)} counts as ${monthName(month)}'s commission income.`}</p>}
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

// What the app works out from the commission balance read after each transaction: the month so far, set against what
// Safaricom paid, and the rates it has learned so they can be checked.
function Learned({ estimates, learned, forecast }) {
  return (
    <section className="panel">
      <h2>Commission worked out from your readings</h2>
      {forecast && <p className="commissionForecast"><b>{forecast.label}: expected {money(forecast.forecast)}</b>{" "}
        <span className="muted">{money(forecast.so_far)} so far, about {money(forecast.daily)} a working day, {forecast.days_left} working {forecast.days_left === 1 ? "day" : "days"} until
        the month closes (Sundays closed). Worked out again after every transaction.</span></p>}
      <p className="muted">After each deposit, withdrawal or airtime sale, enter the commission balance on the agent line. The rise is what that
        transaction earned, and the app learns from it. Once an amount has earned the same twice, the box stops showing for it and its
        commission is worked out by itself. If Safaricom changes its rates, the month's figure here stops matching what Safaricom paid.</p>
      <div className="trendTable"><table className="loanRepayments">
        <caption>What the app worked out, next to what Safaricom paid</caption>
        <thead><tr><th scope="col">Month</th><th scope="col">Worked out by the app</th><th scope="col">Safaricom paid</th><th scope="col">Difference</th></tr></thead>
        <tbody>{estimates.map((m) => (
          <tr key={m.month}>
            <th scope="row">{m.label}{m.current && <small className="muted"> · so far {money(m.earned)}, forecast to month end</small>}</th>
            <td>{money(m.expected)}{m.unknown > 0 && <small className="muted"> · {m.unknown} not worked out yet</small>}</td>
            <td>{m.paid == null ? "Not recorded yet" : money(m.paid)}</td>
            <td>{m.difference == null ? "—" : Math.abs(Number(m.difference)) < 0.5 ? "Same" : `${Number(m.difference) > 0 ? "Paid more" : "Paid less"} by ${money(Math.abs(Number(m.difference)))}`}</td>
          </tr>))}</tbody>
      </table></div>
      {learned.length ? <div className="trendTable"><table className="loanRepayments">
        <caption>What the app has learned</caption>
        <thead><tr><th scope="col">Transaction</th><th scope="col">Amounts seen</th><th scope="col">Commission each</th></tr></thead>
        <tbody>{learned.map((band) => (
          <tr key={`${band.kind}-${band.from}`}>
            <th scope="row">{band.label}</th>
            <td>{band.from === band.to ? money(band.from) : `${money(band.from)} to ${money(band.to)}`}</td>
            <td>{money(band.earned)}{!band.confirmed && <small className="muted"> · still learning</small>}</td>
          </tr>))}</tbody>
      </table></div> : <p className="muted">Nothing learned yet: it starts with the first two readings in a row.</p>}
    </section>
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
      {adding && <RecordForm data={data} canSpend={can("accounting.add_expense")} onCancel={() => setAdding(false)} onSaved={async () => { setAdding(false); await load(); }} />}
      {data.outlets.length === 0 && <Empty>Add an M-Pesa agency outlet on the Agent desk first.</Empty>}
      {data.estimates && <Learned estimates={data.estimates} learned={data.learned || []} forecast={data.forecast} />}
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
