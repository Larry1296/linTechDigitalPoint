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

const planBody = ({ id, deposit, daily_payment, days, commission }) => ({ ...(id ? { id } : {}), deposit, daily_payment, days: Number(days),
  commission: commission === "" || commission == null ? null : commission });

// One plan's fields: a deposit, then so much a day for so many days, and the commission per phone when it is known.
function PlanFields({ plan, title, busy, onChange, onRemove }) {
  return (
    <fieldset disabled={busy} className="mkopaPlanFields">
      <legend>{title}</legend>
      <FormField label={`Deposit (${businessCurrency()})`} type="number" min="0" step="0.01" required value={plan.deposit}
        onChange={(event) => onChange("deposit", event.target.value)} placeholder="e.g. 3899" />
      <FormField label={`Paid each day (${businessCurrency()})`} type="number" min="0.01" step="0.01" required value={plan.daily_payment}
        onChange={(event) => onChange("daily_payment", event.target.value)} placeholder="e.g. 93" />
      <FormField label="For how many days" type="number" min="1" max="3650" step="1" required value={plan.days}
        onChange={(event) => onChange("days", event.target.value)} placeholder="e.g. 365" />
      <FormField label={`Commission per phone (${businessCurrency()})`} type="number" min="0" step="0.01" value={plan.commission}
        onChange={(event) => onChange("commission", event.target.value)} placeholder="If you know it" />
      <p className="muted mkopaPlanTotal">Know the commission? Type it. Not yet? Leave it blank: it is filled in from M-KOPA's payment when M-KOPA pays.</p>
      {plan.learned_commission != null && <p className="muted mkopaPlanTotal">Filled in from M-KOPA's payments: {money(plan.learned_commission)} a phone
        ({count(plan.learned_from, "payment")}). That is the one used; what you type here is kept as your own figure.</p>}
      {plan.deposit !== "" && plan.daily_payment !== "" && plan.days !== "" && <p className="muted mkopaPlanTotal">
        The customer pays M-KOPA {money(planTotal(plan))} in all.</p>}
      {onRemove && <button type="button" className="secondary mkopaSmall" onClick={onRemove}>Remove this plan</button>}
    </fieldset>
  );
}

// Changing a phone: its name and its plans. Changing a plan never changes what phones already paid for earned.
function PhoneForm({ phone, onSaved, onCancel }) {
  const [name, setName] = useState(phone.name);
  const [plans, setPlans] = useState(phone.plans.map((plan) => ({ ...plan, key: String(plan.id), commission: plan.typed_commission ?? "" })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, field, value) => setPlans(plans.map((plan) => (plan.key === key ? { ...plan, [field]: value } : plan)));
  const submit = async (event) => {
    event.preventDefault();
    const dropped = phone.plans.filter((old) => !plans.some((plan) => plan.id === old.id));
    if (dropped.length && !(await confirmAction({ title: `Stop selling ${dropped.length === 1 ? "a plan" : `${dropped.length} plans`} of ${name}?`,
      text: `${dropped.map(planWords).join("; ")}. Phones already sold on it keep their commission.`, confirmButtonText: "Save" }))) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/mkopa/phones/${phone.id}/`, { method: "PATCH", body: JSON.stringify({ name, plans: plans.map(planBody) }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard mkopaPhoneForm" onSubmit={(event) => void submit(event)} aria-label={`Change ${phone.name}`}>
      <h2>Change {phone.name}</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Phone model" value={name} onChange={(event) => setName(event.target.value)} required minLength={2} maxLength={80} autoComplete="off" />
      </fieldset>
      {plans.map((plan, index) => <PlanFields key={plan.key} plan={plan} title={`Plan ${index + 1}`} busy={busy}
        onChange={(field, value) => set(plan.key, field, value)} onRemove={plans.length > 1 ? () => setPlans(plans.filter((p) => p.key !== plan.key)) : null} />)}
      <button type="button" className="secondary" disabled={busy} onClick={() => setPlans([...plans, blankPlan()])}>+ Add {plans.length === 1 ? "a second" : "another"} plan</button>
      <div className="actionRow">
        <button disabled={busy}>Save changes</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not save the phone." message={error} />
    </form>
  );
}

// Adding phones: more of a model you already sell (and maybe another plan for it), or a new model with its plans. Either
// way, how many phones M-KOPA gave you now is recorded with it.
function AddPhonesForm({ phones, onSaved, onCancel }) {
  const known = phones.filter((phone) => phone.active);
  const [mode, setMode] = useState(known.length ? "SAME" : "NEW");
  const [phoneId, setPhoneId] = useState(String(known[0]?.id ?? ""));
  const [name, setName] = useState("");
  const [plans, setPlans] = useState([blankPlan()]);
  const [extra, setExtra] = useState([]);  // new plans for a model already sold
  const [quantity, setQuantity] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const same = mode === "SAME";
  const phone = known.find((p) => String(p.id) === phoneId);
  const taken = !same && phones.find((p) => p.name.trim().toLowerCase() === name.trim().toLowerCase());
  const edit = (list, setList) => (key, field, value) => setList(list.map((plan) => (plan.key === key ? { ...plan, [field]: value } : plan)));
  const pieces = Number(quantity) || 0;
  const nothing = same && !pieces && !extra.length;
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      let id = phone?.id;
      if (same && extra.length) {
        const kept = phone.plans.map((plan) => planBody({ ...plan, commission: plan.typed_commission }));
        await api(`/api/v1/mkopa/phones/${id}/`, { method: "PATCH", body: JSON.stringify({ plans: [...kept, ...extra.map(planBody)] }) });
      }
      if (!same) id = (await api("/api/v1/mkopa/phones/", { method: "POST", body: JSON.stringify({ name, plans: plans.map(planBody) }) })).id;
      if (pieces) await api("/api/v1/mkopa/stock/", { method: "POST", body: JSON.stringify({ phone: id, quantity: pieces, kind: "RECEIVED",
        moved_on: today(), notes: "", idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard mkopaPhoneForm" onSubmit={(event) => void submit(event)} aria-label="Add phones">
      <h2>Add phones</h2>
      {known.length > 0 && <fieldset disabled={busy} className="mkopaChoice">
        <legend>Which phone?</legend>
        <label><input type="radio" name="mode" checked={same} onChange={() => setMode("SAME")} /> A model I already sell</label>
        <label><input type="radio" name="mode" checked={!same} onChange={() => setMode("NEW")} /> A new model</label>
      </fieldset>}
      <fieldset disabled={busy} className="loanFields mkopaPhoneTop">
        {same ? <FormField label="Phone model">
          <select value={phoneId} onChange={(event) => { setPhoneId(event.target.value); setExtra([]); }}>
            {known.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </FormField> : <FormField label="Phone model" value={name} onChange={(event) => setName(event.target.value)} required minLength={2} maxLength={80}
          placeholder="e.g. X30" autoComplete="off" />}
        <FormField label={same ? "How many more M-KOPA gave you" : "How many M-KOPA gave you"} type="number" min="0" step="1"
          value={quantity} onChange={(event) => setQuantity(event.target.value)} placeholder="0" />
      </fieldset>
      {taken && <p className="formNotice formNoticeError">{taken.name} is already in your list. Choose “A model I already sell” to add more of it.</p>}
      {same && phone && <>
        <p className="muted">{phone.name} is sold on {count(phone.plans.length, "plan")}: {phone.plans.map(planWords).join("; ")}.</p>
        {extra.map((plan, index) => <PlanFields key={plan.key} plan={plan} title={`New plan ${index + 1} for ${phone.name}`} busy={busy}
          onChange={(field, value) => edit(extra, setExtra)(plan.key, field, value)}
          onRemove={() => setExtra(extra.filter((p) => p.key !== plan.key))} />)}
        <button type="button" className="secondary" disabled={busy} onClick={() => setExtra([...extra, blankPlan()])}>+ Add another plan for {phone.name}</button>
      </>}
      {!same && <>
        {plans.map((plan, index) => <PlanFields key={plan.key} plan={plan} title={`Plan ${index + 1}`} busy={busy}
          onChange={(field, value) => edit(plans, setPlans)(plan.key, field, value)} onRemove={plans.length > 1 ? () => setPlans(plans.filter((p) => p.key !== plan.key)) : null} />)}
        <button type="button" className="secondary" disabled={busy} onClick={() => setPlans([...plans, blankPlan()])}>+ Add {plans.length === 1 ? "a second" : "another"} plan</button>
      </>}
      <div className="actionRow">
        <button disabled={busy || nothing || Boolean(taken)}>{same ? (pieces ? `Add ${count(pieces, "phone")}` : "Save") : "Add phone"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      {nothing && <p className="muted">Say how many more {phone?.name} M-KOPA gave you, or add another plan.</p>}
      <FormError title="Could not add the phones." message={error} />
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

// Commission M-KOPA paid you: it is profit from the day it arrives, in the place it was paid to. Usually what it paid for
// each phone, typed against that phone (each one tells the app its plan's commission outright); or one total for the
// phones ticked, when M-KOPA's statement gives only a total (server mkopa/learning.py works the plans out from those).
function CommissionForm({ methods, unpaid, only, onSaved, onCancel }) {
  const [method, setMethod] = useState("MPESA");
  const [paidOn, setPaidOn] = useState(today());
  const [mode, setMode] = useState("EACH");
  const [total, setTotal] = useState("");
  const [ticked, setTicked] = useState(() => new Set(only ? [only] : unpaid.filter((sale) => sale.sold_on <= today()).map((sale) => sale.id)));
  const [amounts, setAmounts] = useState(() => Object.fromEntries(unpaid.map((sale) => [sale.id, sale.commission != null ? String(Number(sale.commission)) : ""])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const each = mode === "EACH";
  const chosen = unpaid.filter((sale) => ticked.has(sale.id));
  const missing = each && chosen.some((sale) => amounts[sale.id] === "");
  const sum = chosen.reduce((value, sale) => value + (Number(amounts[sale.id]) || 0), 0);
  const known = chosen.filter((sale) => sale.commission != null);
  const expected = known.reduce((value, sale) => value + Number(sale.commission), 0);
  const paid = each ? sum : Number(total) || 0;
  const gap = paid - expected;
  const toggle = (id) => { const next = new Set(ticked); if (next.has(id)) next.delete(id); else next.add(id); setTicked(next); };
  const blocked = busy || (each ? !chosen.length || missing || sum <= 0 : paid <= 0);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: `Record ${money(paid)} commission from M-KOPA?`,
      text: `For ${chosen.length === 1 ? `${chosen[0].phone} sold to ${chosen[0].customer_name}` : count(chosen.length, "phone")}. It counts as profit on ${date(paidOn)} `
        + `and goes into your ${Object.fromEntries(methods)[method].toLowerCase()}.`, confirmButtonText: "Record commission" }))) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/mkopa/commission/", { method: "POST", body: JSON.stringify({ reference: values.reference, notes: values.notes, paid_on: paidOn, method,
        ...(each ? { amounts: chosen.map((sale) => ({ sale: sale.id, amount: amounts[sale.id] })) } : { amount: total, sales: chosen.map((sale) => sale.id) }),
        idempotency_key: crypto.randomUUID() }) });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="Record commission">
      <h2>Commission M-KOPA paid you</h2>
      <fieldset disabled={busy} className="mkopaChoice">
        <legend>How did M-KOPA pay?</legend>
        <label><input type="radio" name="mode" checked={each} onChange={() => setMode("EACH")} /> An amount for each phone</label>
        <label><input type="radio" name="mode" checked={!each} onChange={() => setMode("TOTAL")} /> One total for several phones</label>
      </fieldset>
      <fieldset disabled={busy} className="mkopaCovers">
        <legend>Phones M-KOPA paid for</legend>
        {unpaid.length ? <>
          <div className="mkopaCoverTools">
            <span className="muted">{count(chosen.length, "phone")} ticked</span>
            <button type="button" className="secondary mkopaSmall" onClick={() => setTicked(new Set(unpaid.filter((sale) => sale.sold_on <= paidOn).map((sale) => sale.id)))}>Tick all</button>
            <button type="button" className="secondary mkopaSmall" onClick={() => setTicked(new Set())}>Tick none</button>
          </div>
          <ul className="mkopaPayList">{unpaid.map((sale) => {
            const on = ticked.has(sale.id);
            return (
              <li key={sale.id} className={on ? "on" : undefined}>
                <label className="mkopaPayWho">
                  <input type="checkbox" checked={on} disabled={sale.sold_on > paidOn} onChange={() => toggle(sale.id)} />
                  <span><strong>{sale.phone}</strong> · {sale.customer_name}<small>Sold {date(sale.sold_on)} · {planWords(sale)}</small></span>
                </label>
                <span className="mkopaPayExpected"><small>Expected</small>{sale.commission != null ? money(sale.commission) : "Not known yet"}</span>
                {each && <label className="mkopaPayAmount"><small>M-KOPA paid ({businessCurrency()})</small>
                  <input type="number" min="0" step="0.01" inputMode="decimal" required={on} disabled={!on} value={amounts[sale.id]}
                    aria-label={`What M-KOPA paid for the ${sale.phone} sold to ${sale.customer_name}`}
                    onChange={(event) => setAmounts({ ...amounts, [sale.id]: event.target.value })} /></label>}
              </li>);
          })}</ul>
        </> : <p className="muted">Every phone sold is already paid for. Record it as one total: it still counts as commission received.</p>}
      </fieldset>
      <fieldset disabled={busy} className="loanFields">
        {each ? <div className="mkopaPayTotal"><span>Total M-KOPA paid</span><strong>{money(sum)}</strong></div>
          : <FormField label={`Total M-KOPA paid (${businessCurrency()})`} type="number" min="0.01" step="0.01" required value={total}
            onChange={(event) => setTotal(event.target.value)} />}
        <FormField label="Paid into">
          <select value={method} onChange={(event) => setMethod(event.target.value)}>{methods.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </FormField>
        <FormField label="Date paid" type="date" max={today()} value={paidOn} required onChange={(event) => setPaidOn(event.target.value)} />
        <FormField label={method === "MPESA" ? "M-Pesa code (optional)" : "Reference (optional)"} name="reference" maxLength={120} autoComplete="off" />
        <FormField label="Note (optional)" name="notes" maxLength={300} autoComplete="off" placeholder="e.g. week 45 commission" />
      </fieldset>
      {chosen.length > 0 && known.length > 0 && paid > 0 && <p className="commissionCompare" role="status">
        The app expected {money(expected)} for {count(known.length, "phone")}.{" "}
        {Math.abs(gap) < 0.5 || known.length < chosen.length ? "" : `M-KOPA paid ${money(Math.abs(gap))} ${gap > 0 ? "more" : "less"}; the app adjusts to it.`}
        {known.length < chosen.length ? `${count(chosen.length - known.length, "phone")} not known yet: learned from this payment.` : ""}
      </p>}
      {missing && <p className="muted">Type what M-KOPA paid for each ticked phone (0 if it paid nothing for one).</p>}
      <div className="actionRow">
        <button disabled={blocked}>Record commission</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
      <FormError title="Could not record the commission." message={error} />
    </form>
  );
}

// A plan in a few words for tables: "KSh 3,899 deposit + KSh 93 a day × 365 days".
const planShort = (plan) => `${money(plan.deposit)} deposit + ${money(plan.daily_payment)} a day × ${plan.days} days`;
const SOURCE = { LEARNED: (plan) => `Learned from ${count(plan.learned_from, "payment")}`, TYPED: () => "Typed by you" };

// One figure, its label above it and a line saying what it means, so each value reads with its own label.
function Stat({ label, value, note, tone }) {
  return <div className={`mkopaStat${tone ? ` ${tone}` : ""}`}><dt>{label}</dt><dd><strong>{value}</strong>{note && <span>{note}</span>}</dd></div>;
}

// A card: a heading on the left, an optional figure or button on the right, then its content.
function Card({ id, title, aside, children, className = "" }) {
  return (
    <section className={`mkopaCard ${className}`} aria-labelledby={id}>
      <header className="mkopaCardHead"><h2 id={id}>{title}</h2>{aside && <div className="mkopaCardAside">{aside}</div>}</header>
      {children}
    </section>
  );
}

// A table cell with a main line and a smaller line under it (both stay together on a phone's labelled card).
const Two = ({ main, sub }) => <span className="mkopaTwo"><span>{main}</span>{sub && <small>{sub}</small>}</span>;

// "If I sell this many, what do I earn?": a number for each plan, the commission added up as you type.
function EarningsCalculator({ phones }) {
  const plans = phones.filter((phone) => phone.active).flatMap((phone) => phone.plans.map((plan, index) => ({ ...plan, phone: phone.name, number: index + 1 })))
    .filter((plan) => plan.commission != null);
  const [counts, setCounts] = useState({});
  if (!plans.length) return null;
  const total = plans.reduce((sum, plan) => sum + (Number(counts[plan.id]) || 0) * Number(plan.commission), 0);
  const phonesCount = plans.reduce((sum, plan) => sum + (Number(counts[plan.id]) || 0), 0);
  return (
    <Card id="mkopa-calc-heading" title="What would I earn?" aside={<span className="mkopaAsideFigure">{money(total)}</span>}>
      <p className="muted mkopaLead">Type how many phones you expect to sell on each plan, for a week or a month. Each plan's commission is the one
        learned from M-KOPA's payments, or the one you typed.</p>
      <div className="mkopaTableWrap"><table className="mkopaTable">
        <thead><tr><th scope="col">Phone</th><th scope="col">Plan</th><th scope="col" className="num">Commission each</th>
          <th scope="col" className="num">How many</th><th scope="col" className="num">You earn</th></tr></thead>
        <tbody>{plans.map((plan) => (
          <tr key={plan.id}>
            <th scope="row">{plan.phone}</th>
            <td><Two main={`Plan ${plan.number}`} sub={planShort(plan)} /></td>
            <td className="num">{money(plan.commission)}</td>
            <td className="num"><input className="mkopaCount" aria-label={`How many ${plan.phone} on ${planWords(plan)}`} type="number" min="0" step="1"
              inputMode="numeric" placeholder="0" value={counts[plan.id] ?? ""} onChange={(event) => setCounts({ ...counts, [plan.id]: event.target.value })} /></td>
            <td className="num">{money((Number(counts[plan.id]) || 0) * Number(plan.commission))}</td>
          </tr>))}</tbody>
        <tfoot><tr><th scope="row" colSpan={3}>Total</th><td className="num">{count(phonesCount, "phone")}</td><td className="num"><strong>{money(total)}</strong></td></tr></tfoot>
      </table></div>
    </Card>
  );
}

function PhonePlans({ phone, seeMoney, canSetUp, onEdit }) {
  return (
    <article className={`mkopaPhone${phone.active ? "" : " mkopaOff"}`} aria-labelledby={`mkopa-phone-${phone.id}`}>
      <header className="mkopaPhoneHead">
        <h3 id={`mkopa-phone-${phone.id}`}>{phone.name}</h3>
        <ul className="mkopaChips" aria-label={`${phone.name} in numbers`}>
          {!phone.active && <li className="off">Not sold now</li>}
          <li>{count(phone.sold, "phone")} sold</li>
          {phone.tracks_stock && <li className={phone.in_hand < 0 ? "warn" : undefined}>{phone.in_hand} in hand</li>}
          <li>{count(phone.plans.length, "plan")}</li>
        </ul>
        {canSetUp && <button type="button" className="secondary mkopaSmall" onClick={onEdit} aria-label={`Change ${phone.name}`}>Change</button>}
      </header>
      {phone.tracks_stock && phone.in_hand < 0 && <p className="formNotice formNoticeError">More {phone.name} sold than M-KOPA gave you: record the phones you received.</p>}
      <div className="mkopaTableWrap"><table className="mkopaTable">
        <caption className="visuallyHidden">{phone.name} plans</caption>
        <thead><tr><th scope="col">Plan</th><th scope="col" className="num">Deposit</th><th scope="col" className="num">Each day</th>
          <th scope="col" className="num">Days</th><th scope="col" className="num">Customer pays in all</th>
          {seeMoney && <th scope="col" className="num">Commission per phone</th>}<th scope="col" className="num">Sold</th>
          {seeMoney && <th scope="col" className="num">M-KOPA paid for them</th>}</tr></thead>
        <tbody>{phone.plans.map((plan, index) => (
          <tr key={plan.id}>
            <th scope="row">Plan {index + 1}</th>
            <td className="num">{money(plan.deposit)}</td><td className="num">{money(plan.daily_payment)}</td><td className="num">{plan.days}</td>
            <td className="num">{money(plan.total_price)}</td>
            {seeMoney && <td className="num"><Two main={plan.commission != null ? <strong>{money(plan.commission)}</strong> : "Not known yet"}
              sub={SOURCE[plan.commission_source]?.(plan) || "Learned when M-KOPA pays"} /></td>}
            <td className="num">{plan.sold}</td>
            {seeMoney && <td className="num">{plan.paid_phones ? <Two main={money(plan.received)} sub={`for ${count(plan.paid_phones, "phone")}`} /> : "—"}</td>}
          </tr>))}</tbody>
      </table></div>
    </article>
  );
}

// Where a phone's commission stands: paid (and when), expected, not known yet, or the sale was undone.
function SaleStatus({ sale }) {
  if (sale.reversed_at) return <Two main={<span className="mkopaPill off">Undone</span>} sub={sale.reverse_reason} />;
  if (sale.commission_paid) return <Two main={<span className="mkopaPill paid">Paid</span>} sub={date(sale.paid_on)} />;
  if (sale.commission == null) return <span className="mkopaPill unknown">Not known yet</span>;
  return <span className="mkopaPill due">Expected</span>;
}

export function MkopaPage() {
  const { user } = useAuth();
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);  // which form: sell, stock, commission, phone, or a phone being changed
  const [problem, setProblem] = useState("");
  const [payFor, setPayFor] = useState(null);  // one phone sold whose commission is being recorded from its row
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
  // "Plan 2" for a sale, numbered as on its phone's card.
  const planNumber = useMemo(() => Object.fromEntries((data?.phones || []).flatMap((phone) => [...phone.plans, ...phone.old_plans].map((plan, index) => [plan.id, index + 1]))), [data]);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const seeMoney = data.can_see_money;
  const summary = data.summary;
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const editing = typeof open === "number" ? phonesById[open] : null;
  const live = data.sales.filter((sale) => !sale.reversed_at).length;
  return (
    <div className="mkopaPage">
      <header className="mkopaHead">
        <div>
          <h1>M-KOPA phones</h1>
          <p className="muted">The phones are M-KOPA's, and customers pay M-KOPA their deposit and daily payments. Yours is the commission M-KOPA pays
            for each phone you sell: business profit, like M-Pesa commission and interest on investments, counted when M-KOPA pays it.</p>
        </div>
        {!open && <div className="mkopaActions">
          {can("mkopa.add_mkopasale") && data.phones.some((p) => p.active && p.plans.length) && <button type="button" onClick={() => setOpen("sell")}>Sell a phone</button>}
          {data.can_record_commission && <button type="button" className="secondary" onClick={() => { setPayFor(null); setOpen("commission"); }}>Commission M-KOPA paid</button>}
          {can("mkopa.add_mkopastock") && data.phones.some((p) => p.active) && <button type="button" className="secondary" onClick={() => setOpen("stock")}>Phones from M-KOPA</button>}
          {data.can_set_up && <button type="button" className="secondary" onClick={() => setOpen("phone")}>Add phones</button>}
        </div>}
      </header>

      {seeMoney && summary && <dl className="mkopaStats">
        <Stat label="M-KOPA has paid you" value={money(summary.commission_paid)} note="Business profit, in the dashboard's profit" tone="good" />
        <Stat label="M-KOPA still owes you" value={money(summary.commission_owed)}
          note={summary.unpaid_phones ? `For ${count(summary.unpaid_phones - summary.unknown_phones, "phone")} not paid yet${summary.unknown_phones
            ? `; ${summary.unknown_phones} more not known yet` : ""}` : "Every phone sold is paid for"} tone={summary.unknown_phones ? "warn" : undefined} />
        <Stat label="Commission earned" value={money(summary.commission_earned)} note={`Paid and still owed, ${count(summary.phones_sold, "phone")} sold`} />
        <Stat label="This month" value={money(summary.month_commission)} note={`${count(summary.month_sold, "phone")} sold`} />
      </dl>}

      {open === "sell" && <SellForm phones={data.phones} seeMoney={seeMoney} onSaved={saved} onCancel={() => setOpen(null)} />}
      {open === "stock" && <StockForm phones={data.phones} onSaved={saved} onCancel={() => setOpen(null)} />}
      {open === "commission" && <CommissionForm key={payFor ?? "all"} methods={data.methods} unpaid={data.unpaid || []} only={payFor}
        onSaved={async () => { setPayFor(null); await saved(); }} onCancel={() => { setPayFor(null); setOpen(null); }} />}
      {open === "phone" && <AddPhonesForm phones={data.phones} onSaved={saved} onCancel={() => setOpen(null)} />}
      {editing && <PhoneForm key={editing.id} phone={editing} onSaved={saved} onCancel={() => setOpen(null)} />}
      <FormError title="Could not undo." message={problem} />

      <Card id="mkopa-phones-heading" title="Phones and plans" aside={data.phones.length ? <span className="muted">{count(data.phones.length, "phone")}</span> : null}>
        {data.phones.length ? <div className="mkopaPhones">{data.phones.map((phone) => <PhonePlans key={phone.id} phone={phone} seeMoney={seeMoney}
          canSetUp={data.can_set_up} onEdit={() => setOpen(phone.id)} />)}</div>
          : <Empty>No phones yet. {data.can_set_up ? "Add each phone M-KOPA gives you to sell, such as X30, with its plans." : "The owner adds them."}</Empty>}
      </Card>

      {seeMoney && <EarningsCalculator phones={data.phones} />}

      <Card id="mkopa-sales-heading" title="Phones sold" aside={<span className="muted">{count(live, "phone")}</span>}>
        {data.sales.length ? <div className="mkopaTableWrap"><table className="mkopaTable">
          <thead><tr><th scope="col">Date</th><th scope="col">Customer</th><th scope="col">Phone</th><th scope="col">IMEI</th>
            {seeMoney && <th scope="col" className="num">Commission</th>}{seeMoney && <th scope="col">Status</th>}<th scope="col">Sold by</th>
            {data.can_undo && <th scope="col" className="actions"><span className="visuallyHidden">Actions</span></th>}</tr></thead>
          <tbody>{data.sales.map((sale) => (
            <tr key={sale.id} className={sale.reversed_at ? "mkopaUndone" : undefined}>
              <td>{date(sale.sold_on)}</td>
              <td><Two main={sale.customer_name} sub={sale.customer_phone} /></td>
              <td><Two main={`${sale.phone} · Plan ${planNumber[sale.plan_id] ?? "—"}`} sub={planShort(sale)} /></td>
              <td><span className="mkopaMono">{sale.imei || "—"}</span></td>
              {seeMoney && <td className="num">{sale.commission != null ? money(sale.commission) : "—"}</td>}
              {seeMoney && <td><span className="mkopaStatusCell"><SaleStatus sale={sale} />
                {data.can_record_commission && !sale.reversed_at && !sale.commission_paid && <button type="button" className="linkButton mkopaLink"
                  aria-label={`Record commission for the ${sale.phone} sold to ${sale.customer_name}`}
                  onClick={() => { setPayFor(sale.id); setOpen("commission"); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Record commission</button>}</span></td>}
              <td>{sale.sold_by || "—"}</td>
              {data.can_undo && <td className="actions">{!sale.reversed_at && !sale.commission_paid && <button type="button" className="secondary mkopaSmall"
                onClick={() => void undo(`Undo the ${sale.phone} sold to ${sale.customer_name}?`, "It no longer earns commission and the phone is back in hand.",
                  `/api/v1/mkopa/sales/${sale.id}/undo/`)}>Undo</button>}</td>}
            </tr>))}</tbody>
        </table></div> : <Empty>No phones sold yet.</Empty>}
      </Card>

      {seeMoney && <Card id="mkopa-paid-heading" title="Commission M-KOPA paid" aside={<span className="mkopaAsideFigure">{money(summary.commission_paid)}</span>}>
        {data.commissions.length ? <div className="mkopaTableWrap"><table className="mkopaTable">
          <thead><tr><th scope="col">Date</th><th scope="col" className="num">Amount</th><th scope="col">For</th><th scope="col">Paid into</th>
            <th scope="col">Reference</th><th scope="col">Note</th>{data.can_record_commission && <th scope="col" className="actions"><span className="visuallyHidden">Actions</span></th>}</tr></thead>
          <tbody>{data.commissions.map((row) => (
            <tr key={row.id} className={row.reversed_at ? "mkopaUndone" : undefined}>
              <td>{date(row.paid_on)}</td>
              <td className="num"><Two main={money(row.amount)} sub={row.reversed_at ? `Undone: ${row.reverse_reason}` : ""} /></td>
              <td>{row.phones ? (row.itemised ? <ul className="mkopaPaidPhones">{row.for_phones.map((p) => <li key={p.sale}>
                <span>{p.phone} · {p.customer_name}</span><span>{money(p.amount)}</span></li>)}</ul>
                : <Two main={count(row.phones, "phone")} sub={`${row.phone_names.join(", ")} · one total`} />) : "—"}</td>
              <td>{row.method_name}</td><td><span className="mkopaMono">{row.reference || "—"}</span></td><td>{row.notes || "—"}</td>
              {data.can_record_commission && <td className="actions">{!row.reversed_at && <button type="button" className="secondary mkopaSmall" onClick={() => void undo(`Undo the ${money(row.amount)} commission?`,
                `It comes back out of your ${row.method_name.toLowerCase()} and your profit, M-KOPA owes it again, and the app stops learning from it.`, `/api/v1/mkopa/commission/${row.id}/undo/`)}>Undo</button>}</td>}
            </tr>))}</tbody>
        </table></div> : <Empty>No commission recorded yet. When M-KOPA pays you, record it here.</Empty>}
      </Card>}

      {data.stock.length > 0 && <Card id="mkopa-stock-heading" title="Phones received and given back" className="mkopaQuiet"
        aside={<span className="muted">{count(data.stock.length, "entry", "entries")}</span>}>
        <div className="mkopaTableWrap"><table className="mkopaTable">
          <thead><tr><th scope="col">Date</th><th scope="col">Phone</th><th scope="col" className="num">Phones</th><th scope="col">Note</th><th scope="col">Recorded by</th>
            {data.can_set_up && <th scope="col" className="actions"><span className="visuallyHidden">Actions</span></th>}</tr></thead>
          <tbody>{data.stock.map((move) => (
            <tr key={move.id} className={move.reversed_at ? "mkopaUndone" : undefined}>
              <td>{date(move.moved_on)}</td><td>{move.phone}</td>
              <td className="num"><Two main={move.quantity > 0 ? `${move.quantity} received` : `${-move.quantity} given back`} sub={move.reversed_at ? `Undone: ${move.reverse_reason}` : ""} /></td>
              <td>{move.notes || "—"}</td><td>{move.recorded_by || "—"}</td>
              {data.can_set_up && <td className="actions">{!move.reversed_at && <button type="button" className="secondary mkopaSmall" onClick={() => void undo("Undo this entry?",
                "The phones in hand go back to what they were before it.", `/api/v1/mkopa/stock/${move.id}/undo/`)}>Undo</button>}</td>}
            </tr>))}</tbody>
        </table></div>
      </Card>}

      {seeMoney && <div className="mkopaCard mkopaBooks"><PartBooks part="MKOPA" refreshKey={summary?.commission_paid} /></div>}
    </div>
  );
}
