import { useEffect, useMemo, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { PartBooks } from "../admin/PartBooks";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const date = (value) => (value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const today = () => new Date().toLocaleDateString("en-CA");
const count = (n, one, many = `${one}s`) => `${Number(n).toLocaleString()} ${Number(n) === 1 ? one : many}`;
// A plan in the words a customer hears: "3,899 deposit, then 93 a day for 365 days".
export const planWords = (plan) => `${money(plan.deposit)} deposit, then ${money(plan.daily_payment)} a day for ${count(plan.days, "day")}`;
export const planTotal = (plan) => Number(plan.deposit) + Number(plan.daily_payment) * Number(plan.days);
const blankPlan = () => ({ key: crypto.randomUUID(), deposit: "", daily_payment: "", days: "", commission: "" });

// A phone and its plans: one or two ways to pay (deposit, then so much a day for so many days), and the commission
// M-KOPA pays you for each phone sold on each plan. Changing a plan later never changes what earlier sales earned.
function PhoneForm({ phone, onSaved, onCancel }) {
  const [name, setName] = useState(phone?.name || "");
  const [plans, setPlans] = useState(phone ? phone.plans.map((plan) => ({ ...plan, key: String(plan.id), commission: plan.typed_commission ?? "" })) : [blankPlan()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, field, value) => setPlans(plans.map((plan) => (plan.key === key ? { ...plan, [field]: value } : plan)));
  const submit = async (event) => {
    event.preventDefault();
    const body = { name, plans: plans.map(({ id, deposit, daily_payment, days, commission }) => ({ ...(id ? { id } : {}), deposit, daily_payment, days: Number(days), commission: commission === "" || commission == null ? null : commission })) };
    const dropped = phone ? phone.plans.filter((old) => !plans.some((plan) => plan.id === old.id)) : [];
    if (dropped.length && !(await confirmAction({ title: `Stop selling ${dropped.length === 1 ? "a plan" : `${dropped.length} plans`} of ${name}?`,
      text: `${dropped.map(planWords).join("; ")}. Phones already sold on it keep their commission.`, confirmButtonText: "Save" }))) return;
    setBusy(true);
    setError("");
    try {
      await api(phone ? `/api/v1/mkopa/phones/${phone.id}/` : "/api/v1/mkopa/phones/", { method: phone ? "PATCH" : "POST", body: JSON.stringify(body) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard mkopaPhoneForm" onSubmit={(event) => void submit(event)} aria-label={phone ? `Change ${phone.name}` : "Add a phone"}>
      <h2>{phone ? `Change ${phone.name}` : "Add an M-KOPA phone"}</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Phone" value={name} onChange={(event) => setName(event.target.value)} required minLength={2} maxLength={80}
          placeholder="e.g. X30" autoComplete="off" />
      </fieldset>
      {plans.map((plan, index) => (
        <fieldset key={plan.key} disabled={busy} className="mkopaPlanFields">
          <legend>Plan {index + 1}</legend>
          <FormField label={`Deposit (${businessCurrency()})`} type="number" min="0" step="0.01" required value={plan.deposit}
            onChange={(event) => set(plan.key, "deposit", event.target.value)} placeholder="e.g. 3899" />
          <FormField label={`Paid each day (${businessCurrency()})`} type="number" min="0.01" step="0.01" required value={plan.daily_payment}
            onChange={(event) => set(plan.key, "daily_payment", event.target.value)} placeholder="e.g. 93" />
          <FormField label="For how many days" type="number" min="1" max="3650" step="1" required value={plan.days}
            onChange={(event) => set(plan.key, "days", event.target.value)} placeholder="e.g. 365" />
          <FormField label={`Your commission per phone, if you know it (${businessCurrency()})`} type="number" min="0" step="0.01" value={plan.commission}
            onChange={(event) => set(plan.key, "commission", event.target.value)} placeholder="Blank: the app learns it" />
          {plan.learned_commission != null && <p className="muted mkopaPlanTotal">Learned from M-KOPA's payments: {money(plan.learned_commission)} a phone
            ({count(plan.learned_from, "payment")}). The learned figure is used; what you type here is kept as your own guess.</p>}
          {plan.deposit !== "" && plan.daily_payment !== "" && plan.days !== "" && <p className="muted mkopaPlanTotal">
            The customer pays M-KOPA {money(planTotal(plan))} in all.</p>}
          {plans.length > 1 && <button type="button" className="secondary" onClick={() => setPlans(plans.filter((p) => p.key !== plan.key))}>Remove plan {index + 1}</button>}
        </fieldset>
      ))}
      <button type="button" className="secondary" disabled={busy} onClick={() => setPlans([...plans, blankPlan()])}>+ Add {plans.length === 1 ? "a second" : "another"} plan</button>
      <div className="actionRow">
        <button disabled={busy}>{phone ? "Save changes" : "Add phone"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not save the phone." message={error} />
    </form>
  );
}

// A phone sold: which phone and plan, and who bought it. The customer pays M-KOPA, never you, so no money is taken here.
function SellForm({ phones, seeMoney, onSaved, onCancel }) {
  const selling = phones.filter((phone) => phone.active && phone.plans.length);
  const [phoneId, setPhoneId] = useState(String(selling[0]?.id ?? ""));
  const phone = selling.find((p) => String(p.id) === phoneId);
  const [planId, setPlanId] = useState(String(phone?.plans[0]?.id ?? ""));
  const plan = phone?.plans.find((p) => String(p.id) === planId) || phone?.plans[0];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: `${phone.name} sold to ${values.customer_name}?`,
      text: `${planWords(plan)}, paid to M-KOPA.${seeMoney ? (plan.commission != null ? ` It should earn you ${money(plan.commission)} commission, counted as profit when M-KOPA pays it.`
        : " Its commission is learned from M-KOPA's payments.") : ""}`,
      confirmButtonText: "Record sale" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/mkopa/sales/", { method: "POST", body: JSON.stringify({ ...values, plan: plan.id, idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  if (!selling.length) return <Empty>Add a phone and its plans first.</Empty>;
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="Sell a phone">
      <h2>Sell a phone</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Phone">
          <select value={phoneId} onChange={(event) => { setPhoneId(event.target.value); setPlanId(String(selling.find((p) => String(p.id) === event.target.value)?.plans[0]?.id ?? "")); }}>
            {selling.map((p) => <option key={p.id} value={p.id}>{p.name}{p.tracks_stock ? ` (${p.in_hand} in hand)` : ""}</option>)}
          </select>
        </FormField>
        {phone.plans.length > 1 ? <FormField label="Plan the customer chose">
          <select value={String(plan.id)} onChange={(event) => setPlanId(event.target.value)}>
            {phone.plans.map((p) => <option key={p.id} value={p.id}>{planWords(p)}</option>)}
          </select>
        </FormField> : <p className="muted mkopaOnePlan">Plan: {planWords(plan)}</p>}
        <FormField label="Customer's name" name="customer_name" required minLength={2} maxLength={120} autoComplete="off" />
        <FormField label="Customer's phone number (optional)" name="customer_phone" type="tel" maxLength={30} autoComplete="off" />
        <FormField label="IMEI (optional)" name="imei" inputMode="numeric" maxLength={30} autoComplete="off" placeholder="On the box, or dial *#06#" />
        <FormField label="Date sold" name="sold_on" type="date" max={today()} defaultValue={today()} required />
      </fieldset>
      <p className="muted">The customer pays M-KOPA {money(planTotal(plan))} in all{seeMoney && plan.commission != null ? `; you should earn ${money(plan.commission)} commission` : ""}.</p>
      <div className="actionRow">
        <button disabled={busy}>Record sale</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the sale." message={error} />
    </form>
  );
}

// Phones M-KOPA handed you, or that you gave back. They stay M-KOPA's, so they are counted here and not in your stock.
function StockForm({ phones, onSaved, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/mkopa/stock/", { method: "POST", body: JSON.stringify({ ...values, phone: Number(values.phone), quantity: Number(values.quantity),
        idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="Phones received">
      <h2>Phones from M-KOPA</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="What happened">
          <select name="kind" defaultValue="RECEIVED"><option value="RECEIVED">M-KOPA gave me phones</option><option value="RETURNED">I gave phones back</option></select>
        </FormField>
        <FormField label="Phone">
          <select name="phone">{phones.filter((p) => p.active).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.in_hand} in hand)</option>)}</select>
        </FormField>
        <FormField label="How many" name="quantity" type="number" min="1" step="1" required defaultValue="1" />
        <FormField label="Date" name="moved_on" type="date" max={today()} defaultValue={today()} required />
        <FormField label="Note (optional)" name="notes" maxLength={300} autoComplete="off" />
      </fieldset>
      <p className="muted">The phones are M-KOPA's until customers pay them off, so they are not your stock and do not change your money.</p>
      <div className="actionRow">
        <button disabled={busy}>Save</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not save." message={error} />
    </form>
  );
}

// Commission M-KOPA paid you: it is profit from the day it arrives, in the place it was paid to. Ticking the phones it
// was for teaches the app each plan's commission (server mkopa/learning.py), so the next phones sold are expected right.
function CommissionForm({ methods, unpaid, onSaved, onCancel }) {
  const [method, setMethod] = useState("MPESA");
  const [paidOn, setPaidOn] = useState(today());
  const [amount, setAmount] = useState("");
  const [ticked, setTicked] = useState(() => new Set(unpaid.filter((sale) => sale.sold_on <= today()).map((sale) => sale.id)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const chosen = unpaid.filter((sale) => ticked.has(sale.id));
  const known = chosen.filter((sale) => sale.commission != null);
  const expected = known.reduce((sum, sale) => sum + Number(sale.commission), 0);
  const unknown = chosen.length - known.length;
  const gap = (Number(amount) || 0) - expected;
  const toggle = (id) => { const next = new Set(ticked); if (next.has(id)) next.delete(id); else next.add(id); setTicked(next); };
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: `Record ${money(amount)} commission from M-KOPA?`,
      text: `For ${count(chosen.length, "phone")} sold. It counts as profit on ${date(paidOn)} and goes into your ${Object.fromEntries(methods)[method].toLowerCase()}.`
        + (chosen.length ? " The app learns each plan's commission from it." : ""),
      confirmButtonText: "Record commission" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/mkopa/commission/", { method: "POST", body: JSON.stringify({ ...values, amount, paid_on: paidOn, method,
        sales: chosen.map((sale) => sale.id), idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="Record commission">
      <h2>Commission M-KOPA paid you</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label={`Amount paid (${businessCurrency()})`} type="number" min="0.01" step="0.01" required value={amount}
          onChange={(event) => setAmount(event.target.value)} />
        <FormField label="Paid into">
          <select value={method} onChange={(event) => setMethod(event.target.value)}>{methods.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </FormField>
        <FormField label="Date paid" type="date" max={today()} value={paidOn} required onChange={(event) => setPaidOn(event.target.value)} />
        <FormField label={method === "MPESA" ? "M-Pesa code (optional)" : "Reference (optional)"} name="reference" maxLength={120} autoComplete="off" />
        <FormField label="Note (optional)" name="notes" maxLength={300} autoComplete="off" placeholder="e.g. week 45 commission" />
      </fieldset>
      <fieldset disabled={busy} className="mkopaCovers">
        <legend>Phones this payment is for</legend>
        {unpaid.length ? <>
          <p className="muted">Tick the phones M-KOPA paid for (its statement lists them). Each payment teaches the app what every phone and plan earns.</p>
          <div className="actionRow">
            <button type="button" className="secondary" onClick={() => setTicked(new Set(unpaid.filter((sale) => sale.sold_on <= paidOn).map((sale) => sale.id)))}>Tick all</button>
            <button type="button" className="secondary" onClick={() => setTicked(new Set())}>Tick none</button>
          </div>
          <ul className="mkopaCoverList">{unpaid.map((sale) => (
            <li key={sale.id}><label>
              <input type="checkbox" checked={ticked.has(sale.id)} disabled={sale.sold_on > paidOn} onChange={() => toggle(sale.id)} />
              <span>{sale.phone} · {sale.customer_name} · sold {date(sale.sold_on)}<small className="muted"> · {planWords(sale)}
                {sale.commission != null ? ` · expected ${money(sale.commission)}` : " · not known yet"}</small></span>
            </label></li>))}</ul>
        </> : <p className="muted">Every phone sold is already paid for. The payment is still recorded as commission received.</p>}
      </fieldset>
      {chosen.length > 0 && <p className="commissionCompare" role="status">
        {known.length ? `The app expected ${money(expected)} for ${count(known.length, "phone")}` : "The app does not know these phones' commission yet"}
        {unknown ? `${known.length ? ";" : ","} ${count(unknown, "phone")} not known yet, learned from this payment` : ""}.
        {Number(amount) > 0 && known.length > 0 && !unknown && (Math.abs(gap) < 0.5 ? " M-KOPA paid the same." : ` M-KOPA paid ${money(Math.abs(gap))} ${gap > 0 ? "more" : "less"}; the app adjusts to it.`)}
      </p>}
      <div className="actionRow">
        <button disabled={busy}>Record commission</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the commission." message={error} />
    </form>
  );
}

// "If I sell this many, what do I earn?": a number for each plan, the commission added up as you type.
function EarningsCalculator({ phones }) {
  const plans = phones.filter((phone) => phone.active).flatMap((phone) => phone.plans.map((plan) => ({ ...plan, phone: phone.name })))
    .filter((plan) => plan.commission != null);
  const [counts, setCounts] = useState({});
  if (!plans.length) return null;
  const total = plans.reduce((sum, plan) => sum + (Number(counts[plan.id]) || 0) * Number(plan.commission), 0);
  const phonesCount = plans.reduce((sum, plan) => sum + (Number(counts[plan.id]) || 0), 0);
  return (
    <section className="dashCard mkopaCalculator" aria-labelledby="mkopa-calc-heading">
      <h2 id="mkopa-calc-heading">What would I earn?</h2>
      <p className="muted">Type how many phones you expect to sell on each plan, such as this week or this month. It uses each plan's commission as
        learned from M-KOPA's payments (or as you typed it).</p>
      <div className="trendTable"><table>
        <thead><tr><th scope="col">Phone and plan</th><th scope="col">Commission each</th><th scope="col">How many</th><th scope="col">You earn</th></tr></thead>
        <tbody>{plans.map((plan) => (
          <tr key={plan.id}>
            <th scope="row">{plan.phone}<small className="muted"> · {planWords(plan)}</small></th>
            <td>{money(plan.commission)}</td>
            <td><input aria-label={`How many ${plan.phone} on ${planWords(plan)}`} type="number" min="0" step="1" inputMode="numeric"
              value={counts[plan.id] ?? ""} onChange={(event) => setCounts({ ...counts, [plan.id]: event.target.value })} /></td>
            <td>{money((Number(counts[plan.id]) || 0) * Number(plan.commission))}</td>
          </tr>))}</tbody>
        <tfoot><tr><th scope="row">Total</th><td /><td>{count(phonesCount, "phone")}</td><td><strong>{money(total)}</strong></td></tr></tfoot>
      </table></div>
    </section>
  );
}

function PhoneCard({ phone, seeMoney, canSetUp, onEdit }) {
  return (
    <li className={`loanCard mkopaPhone${phone.active ? "" : " muted"}`}>
      <header className="loanCardHead">
        <div>
          <h3>{phone.name}{!phone.active && " (not sold now)"}</h3>
          <p className="muted">{[count(phone.sold, "sold", "sold"), phone.tracks_stock && `${phone.in_hand} in hand`].filter(Boolean).join(" · ")}</p>
        </div>
        {canSetUp && <button type="button" className="secondary" onClick={onEdit}>Change</button>}
      </header>
      {phone.tracks_stock && phone.in_hand < 0 && <p className="formNotice formNoticeError">More {phone.name} sold than M-KOPA gave you: record the phones you received.</p>}
      <div className="trendTable"><table className="mkopaPlans">
        <caption className="visuallyHidden">{phone.name} plans</caption>
        <thead><tr><th scope="col">Plan</th><th scope="col">Deposit</th><th scope="col">Each day</th><th scope="col">Days</th><th scope="col">Customer pays in all</th>
          {seeMoney && <th scope="col">Your commission</th>}<th scope="col">Sold</th>{seeMoney && <th scope="col">M-KOPA paid for them</th>}</tr></thead>
        <tbody>{phone.plans.map((plan, index) => (
          <tr key={plan.id}>
            <th scope="row">Plan {index + 1}</th><td>{money(plan.deposit)}</td><td>{money(plan.daily_payment)}</td><td>{plan.days}</td>
            <td>{money(plan.total_price)}</td>
            {seeMoney && <td>{plan.commission != null ? <strong>{money(plan.commission)}</strong> : "Not known yet"}<small className="muted mkopaSource">{
              plan.commission_source === "LEARNED" ? `learned from ${count(plan.learned_from, "payment")}`
                : plan.commission_source === "TYPED" ? "typed by you" : "learned when M-KOPA pays"}</small></td>}
            <td>{plan.sold}</td>
            {seeMoney && <td>{plan.paid_phones ? `${money(plan.received)} for ${count(plan.paid_phones, "phone")}` : "—"}</td>}
          </tr>))}</tbody>
      </table></div>
    </li>
  );
}

export function MkopaPage() {
  const { user } = useAuth();
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);  // which form: sell, stock, commission, phone, or a phone being changed
  const [problem, setProblem] = useState("");
  const load = async () => {
    try {
      setData(await api("/api/v1/mkopa/"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load);
  const saved = async () => { setOpen(null); await load(); };
  const undo = async (title, text, path) => {
    const values = await askForm({ title, text, confirmButtonText: "Undo", fields: [{ name: "reason", label: "Why", required: true, placeholder: "e.g. recorded twice" }] });
    if (!values) return;
    setProblem("");
    try {
      await api(path, { method: "POST", body: JSON.stringify({ reason: values.reason }) });
      await load();
    } catch (err) {
      setProblem(err.message);
    }
  };
  const phonesById = useMemo(() => Object.fromEntries((data?.phones || []).map((phone) => [phone.id, phone])), [data]);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const seeMoney = data.can_see_money;
  const summary = data.summary;
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const editing = typeof open === "number" ? phonesById[open] : null;
  return (
    <>
      <h1>M-KOPA phones</h1>
      <p className="muted">The phones are M-KOPA's and customers pay M-KOPA their deposit and daily payments. What is yours is the commission M-KOPA pays
        for each phone you sell; it counts as profit when M-KOPA pays it.</p>
      {seeMoney && summary && <dl className="loanFigures mkopaFigures">
        <div><dt>Phones sold</dt><dd>{Number(summary.phones_sold).toLocaleString()}</dd></div>
        <div><dt>Commission earned</dt><dd>{money(summary.commission_earned)}</dd></div>
        <div><dt>M-KOPA has paid you</dt><dd>{money(summary.commission_paid)}</dd></div>
        <div><dt>M-KOPA still owes you</dt><dd><strong>{money(summary.commission_owed)}</strong></dd></div>
        <div><dt>This month</dt><dd>{count(summary.month_sold, "phone")} · {money(summary.month_commission)}</dd></div>
      </dl>}
      {seeMoney && summary?.unknown_phones > 0 && <p className="muted">{count(summary.unknown_phones, "phone")} sold on plans whose commission is not known yet:
        not counted in what M-KOPA owes you. The app learns it when you record M-KOPA's payment for them.</p>}
      {!open && <div className="actionRow mkopaActions">
        {can("mkopa.add_mkopasale") && data.phones.some((p) => p.active && p.plans.length) && <button type="button" onClick={() => setOpen("sell")}>Sell a phone</button>}
        {can("mkopa.add_mkopastock") && data.phones.some((p) => p.active) && <button type="button" className="secondary" onClick={() => setOpen("stock")}>Phones from M-KOPA</button>}
        {data.can_record_commission && <button type="button" className="secondary" onClick={() => setOpen("commission")}>Commission M-KOPA paid</button>}
        {data.can_set_up && <button type="button" className="secondary" onClick={() => setOpen("phone")}>Add a phone</button>}
      </div>}
      {open === "sell" && <SellForm phones={data.phones} seeMoney={seeMoney} onSaved={saved} onCancel={() => setOpen(null)} />}
      {open === "stock" && <StockForm phones={data.phones} onSaved={saved} onCancel={() => setOpen(null)} />}
      {open === "commission" && <CommissionForm methods={data.methods} unpaid={data.unpaid || []} onSaved={saved} onCancel={() => setOpen(null)} />}
      {(open === "phone" || editing) && <PhoneForm key={editing?.id ?? "new"} phone={editing} onSaved={saved} onCancel={() => setOpen(null)} />}
      <FormError title="Could not undo." message={problem} />

      <section aria-labelledby="mkopa-phones-heading">
        <h2 id="mkopa-phones-heading">Phones and plans</h2>
        {data.phones.length ? <ul className="loanList">{data.phones.map((phone) => <PhoneCard key={phone.id} phone={phone} seeMoney={seeMoney}
          canSetUp={data.can_set_up} onEdit={() => setOpen(phone.id)} />)}</ul>
          : <Empty>No phones yet. {data.can_set_up ? "Add each phone M-KOPA gives you to sell, such as X30, with its plans and your commission." : "The owner adds them."}</Empty>}
      </section>

      {seeMoney && <EarningsCalculator phones={data.phones} />}

      <section aria-labelledby="mkopa-sales-heading">
        <h2 id="mkopa-sales-heading">Phones sold</h2>
        {data.sales.length ? <div className="trendTable"><table className="mkopaSales">
          <thead><tr><th scope="col">Date</th><th scope="col">Customer</th><th scope="col">Phone and plan</th><th scope="col">IMEI</th>
            {seeMoney && <th scope="col">Commission</th>}<th scope="col">Sold by</th>{data.can_undo && <th scope="col"><span className="visuallyHidden">Action</span></th>}</tr></thead>
          <tbody>{data.sales.map((sale) => (
            <tr key={sale.id} className={sale.reversed_at ? "muted" : undefined}>
              <td>{date(sale.sold_on)}</td>
              <td>{sale.customer_name}{sale.customer_phone && <small className="muted"> · {sale.customer_phone}</small>}</td>
              <td>{sale.phone}<small className="muted"> · {planWords(sale)}</small>{sale.reversed_at && <small> · undone ({sale.reverse_reason})</small>}</td>
              <td>{sale.imei || "—"}</td>
              {seeMoney && <td>{sale.commission != null ? money(sale.commission) : "Not known yet"}<small className="muted">{sale.reversed_at ? ""
                : sale.commission_paid ? ` · paid ${date(sale.paid_on)}` : " · expected"}</small></td>}
              <td>{sale.sold_by || "—"}</td>
              {data.can_undo && <td>{!sale.reversed_at && <button type="button" className="secondary" onClick={() => void undo(`Undo the ${sale.phone} sold to ${sale.customer_name}?`,
                "It no longer earns commission and the phone is back in hand.", `/api/v1/mkopa/sales/${sale.id}/undo/`)}>Undo</button>}</td>}
            </tr>))}</tbody>
        </table></div> : <Empty>No phones sold yet.</Empty>}
      </section>

      {seeMoney && <section aria-labelledby="mkopa-paid-heading">
        <h2 id="mkopa-paid-heading">Commission M-KOPA paid</h2>
        {data.commissions.length ? <div className="trendTable"><table>
          <thead><tr><th scope="col">Date</th><th scope="col">Amount</th><th scope="col">For</th><th scope="col">Paid into</th><th scope="col">Reference</th><th scope="col">Note</th>
            {data.can_record_commission && <th scope="col"><span className="visuallyHidden">Action</span></th>}</tr></thead>
          <tbody>{data.commissions.map((row) => (
            <tr key={row.id} className={row.reversed_at ? "muted" : undefined}>
              <td>{date(row.paid_on)}</td>
              <td>{money(row.amount)}{row.reversed_at && <small> · undone ({row.reverse_reason})</small>}</td>
              <td>{row.phones ? `${count(row.phones, "phone")} (${row.phone_names.join(", ")})` : "—"}</td>
              <td>{row.method_name}</td><td>{row.reference || "—"}</td><td>{row.notes || "—"}</td>
              {data.can_record_commission && <td>{!row.reversed_at && <button type="button" className="secondary" onClick={() => void undo(`Undo the ${money(row.amount)} commission?`,
                `It comes back out of your ${row.method_name.toLowerCase()} and your profit, M-KOPA owes it again, and the app stops learning from it.`, `/api/v1/mkopa/commission/${row.id}/undo/`)}>Undo</button>}</td>}
            </tr>))}</tbody>
        </table></div> : <Empty>No commission recorded yet. When M-KOPA pays you, record it here.</Empty>}
      </section>}

      {data.stock.length > 0 && <details className="loanSettled">
        <summary>Phones received and given back ({data.stock.length})</summary>
        <div className="trendTable"><table>
          <thead><tr><th scope="col">Date</th><th scope="col">Phone</th><th scope="col">Phones</th><th scope="col">Note</th><th scope="col">By</th>
            {data.can_set_up && <th scope="col"><span className="visuallyHidden">Action</span></th>}</tr></thead>
          <tbody>{data.stock.map((move) => (
            <tr key={move.id} className={move.reversed_at ? "muted" : undefined}>
              <td>{date(move.moved_on)}</td><td>{move.phone}</td>
              <td>{move.quantity > 0 ? `${move.quantity} received` : `${-move.quantity} given back`}{move.reversed_at && <small> · undone ({move.reverse_reason})</small>}</td>
              <td>{move.notes || "—"}</td><td>{move.recorded_by || "—"}</td>
              {data.can_set_up && <td>{!move.reversed_at && <button type="button" className="secondary" onClick={() => void undo("Undo this entry?",
                "The phones in hand go back to what they were before it.", `/api/v1/mkopa/stock/${move.id}/undo/`)}>Undo</button>}</td>}
            </tr>))}</tbody>
        </table></div>
      </details>}

      {seeMoney && <PartBooks part="MKOPA" refreshKey={summary?.commission_paid} />}
    </>
  );
}
