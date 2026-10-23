import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { askForm, confirmAction, showError, showSuccess } from "../../core/ui/alerts";
import { ErrorState, Loading } from "../../components/States";
import "./billing.css";
import { TextBox } from "../../components/forms/TextBox";
import { ProtectedPasswordForm } from "../../core/auth/ProtectedPages";

const MODULE_LABELS = { inventory: "Products & stock", locations: "Shelves & locations", services: "Services & jobs", pos: "Point of sale",
  customers: "Customers", expenses: "Expenses", mpesa: "M-Pesa agency", reports: "Reports", branches: "Branches", staff: "Staff", chama: "Chama" };
const MODEL_LABELS = { GOODS: "Sells goods", SERVICES: "Provides services", MIXED: "Goods and services" };
const money = (amount, currency = "KES") => `${currency} ${Number(amount || 0).toLocaleString()}`;
const dateText = (value) => (value ? new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");

export function statusOf(subscription) {
  if (subscription.complimentary) return { key: "complimentary", label: "Free (platform)", tone: "active" };
  if (subscription.status === "UNCONFIGURED" || !subscription.plan) return { key: "ended", label: "No plan", tone: "ended" };
  if (subscription.ended) return { key: "ended", label: subscription.stored_status === "SUSPENDED" ? "Suspended" : "Ended", tone: "ended" };
  if (subscription.status === "TRIAL") return { key: "trial", label: "Free month", tone: subscription.expiring_soon ? "warn" : "" };
  return { key: "active", label: "Paid", tone: subscription.expiring_soon ? "warn" : "active" };
}

// The platform owner's view of every subscribed business, and the tools to manage subscriptions and plans.
export function PlatformAdminPage() {
  const { user } = useAuth();
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [plan, setPlan] = useState("all");
  const [selected, setSelected] = useState(null);
  const load = useCallback(() => api("/api/v1/tenancy/platform-admin/overview/").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { if (user?.platform_admin) void load(); }, [user, load]);
  const rows = useMemo(() => (data?.businesses || []).filter((row) => {
    const text = `${row.name} ${row.business_type} ${row.owner.name} ${row.owner.username} ${row.owner.email} ${row.owner.phone} ${row.phone}`.toLowerCase();
    return (!query.trim() || text.includes(query.trim().toLowerCase()))
      && (status === "all" || (status === "off" ? !row.active : statusOf(row.subscription).key === status) || (status === "expiring" && row.subscription.expiring_soon))
      && (plan === "all" || row.subscription.plan === plan);
  }), [data, query, status, plan]);
  if (!user?.platform_admin) return <Navigate to="/admin/dashboard" replace />;
  if (error && !data) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const { summary } = data;

  return <section className="platformPage">
    <div><span className="eyebrow">Platform</span><h1>All businesses</h1></div>
    {!summary.mpesa_ready && <p className="billingNote">M-Pesa payments are {summary.mpesa_mode === "off" ? "switched off" : "not fully configured"}. Owners cannot pay in the app until the MPESA_* settings are set on the server; you can still record payments here.</p>}
    {summary.mpesa_mode === "simulate" && summary.mpesa_ready && <p className="billingNote">M-Pesa is in simulate mode (development): payments complete by themselves.</p>}
    <div className="platformStats">
      <div><strong>{summary.businesses}</strong><span>Businesses</span></div>
      <div><strong>{summary.trial}</strong><span>On free month</span></div>
      <div><strong>{summary.paying}</strong><span>Paying</span></div>
      <div><strong>{summary.expiring_soon}</strong><span>Ending within 5 days</span></div>
      <div><strong>{summary.ended}</strong><span>Ended or suspended</span></div>
      <div><strong>{summary.switched_off}</strong><span>Switched off</span></div>
      {Object.entries(summary.by_plan).map(([code, count]) => <div key={code}><strong>{count}</strong><span>On {code === "PRO" ? "Pro" : "Basic"}</span></div>)}
      <div><strong>{money(summary.revenue_this_month, summary.currency)}</strong><span>Paid this month</span></div>
      <div><strong>{money(summary.revenue_total, summary.currency)}</strong><span>Paid in total</span></div>
    </div>

    <div className="platformFilters">
      <label>Search<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Business, owner, phone or email" /></label>
      <label>Status<select value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="all">All</option><option value="trial">Free month</option><option value="active">Paid</option>
        <option value="expiring">Ending within 5 days</option><option value="ended">Ended or suspended</option><option value="complimentary">Free (platform)</option>
        <option value="off">Switched off</option>
      </select></label>
      <label>Plan<select value={plan} onChange={(e) => setPlan(e.target.value)}>
        <option value="all">All</option>{data.plans.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
      </select></label>
    </div>

    <div className="platformTableWrap">
      <table className="platformTable">
        <thead><tr><th>Business</th><th>Owner</th><th>Plan</th><th>Status</th><th>Ends</th><th>Paid in total</th><th>Joined</th></tr></thead>
        <tbody>{rows.map((row) => {
          const view = statusOf(row.subscription);
          return <tr key={row.id} className={selected === row.id ? "selected" : undefined}>
            <td><button type="button" className="linkButton" onClick={() => setSelected(row.id)}>{row.name}</button><small>{row.business_type || "—"}</small></td>
            <td>{row.owner.name || row.owner.username}<small>{[row.owner.phone, row.owner.email].filter(Boolean).join(" · ")}</small></td>
            <td>{row.subscription.plan_name || "—"}</td>
            <td><span className={`statusPill ${view.tone}`}>{view.label}</span>{!row.active && <span className="statusPill ended">Switched off</span>}</td>
            <td>{row.subscription.complimentary ? "Never" : dateText(row.subscription.ends_at)}{!row.subscription.ended && row.subscription.days_left != null && <small>{row.subscription.days_left} days left</small>}</td>
            <td>{money(row.total_paid)}{row.last_paid_at && <small>last {dateText(row.last_paid_at)}</small>}</td>
            <td>{dateText(row.created_at)}</td>
          </tr>;
        })}</tbody>
      </table>
      {!rows.length && <p className="muted" style={{ padding: 16 }}>No businesses match.</p>}
    </div>

    {selected && <BusinessDetail key={selected} id={selected} plans={data.plans} kinds={data.kinds || []} onChanged={load} onClose={() => setSelected(null)}
      onDeleted={() => { setSelected(null); void load(); }} />}

    <h2>Recent payments</h2>
    {data.recent_payments.length ? <div className="platformTableWrap"><table className="platformTable">
      <thead><tr><th>Date</th><th>Business</th><th>Plan</th><th>Amount</th><th>Method</th><th>Status</th><th>Receipt</th></tr></thead>
      <tbody>{data.recent_payments.map((payment) => <tr key={payment.id}>
        <td>{dateText(payment.created_at)}</td><td>{payment.business}</td><td>{payment.plan}</td><td>{money(payment.amount, payment.currency)}</td>
        <td>{payment.method === "MPESA" ? `M-Pesa ${payment.phone}` : "Recorded"}</td>
        <td><span className={`paymentStatus ${payment.status.toLowerCase()}`}>{payment.status.toLowerCase()}</span></td><td>{payment.receipt_number || "—"}</td>
      </tr>)}</tbody>
    </table></div> : <p className="muted">No payments yet.</p>}

    <h2>Plans</h2>
    <p className="muted">Each plan has a standard price. Set a different price for a kind of business (a kibanda pays less than a hardware shop),
      or for one business from its details above. A business pays its own price first, then its kind's, then the standard price.</p>
    <div className="platformPlans">{data.plans.map((item) => <PlanEditor key={item.id} plan={item} kinds={data.kinds || []} onSaved={load} />)}</div>

    <BusinessKinds />
  </section>;
}

const SOURCE = { business: "its own price", kind: "the price for its kind", standard: "the standard price" };
const MODEL_ORDER = ["GOODS", "SERVICES", "MIXED"];

// The kinds of business as a grouped list to choose from (owner-added kinds not yet listed are marked).
function KindOptions({ kinds }) {
  return MODEL_ORDER.map((model) => <optgroup key={model} label={MODEL_LABELS[model]}>
    {kinds.filter((kind) => kind.model === model).map((kind) => <option key={kind.id} value={kind.id}>{kind.label}{kind.listed ? "" : " (not listed)"}</option>)}
  </optgroup>);
}

function BusinessDetail({ id, plans, kinds, onChanged, onClose, onDeleted }) {
  const [row, setRow] = useState();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Deleting needs the administrator's protected pages password; when there is none yet, or it is a week old, it is set here first.
  const [needsPassword, setNeedsPassword] = useState(null);
  const path = `/api/v1/tenancy/platform-admin/businesses/${id}/`;
  const load = useCallback(() => api(path).then(setRow).catch((e) => setError(e.message)), [path]);
  useEffect(() => { void load(); }, [load]);
  if (error && !row) return <ErrorState message={error} retry={load} />;
  if (!row) return <Loading />;
  const change = async (title, method, body, done) => {
    if (!(await confirmAction({ title, text: `${row.name}`, confirmButtonText: "Yes, apply", icon: "question" }))) return;
    setBusy(true);
    try {
      await api(path, { method, body: JSON.stringify(body) });
      await Promise.all([load(), onChanged()]);
      await showSuccess("Done", done);
    } catch (e) {
      await showError("Could not apply the change", e.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    let status;
    try {
      status = (await api("/api/v1/auth/protected/")).protected;
    } catch (e) {
      await showError("Could not delete the business", e.message);
      return;
    }
    if (!status.has_password || status.expired) { setNeedsPassword(status); return; }
    const values = await askForm({ title: `Delete ${row.name} for good?`, confirmButtonText: "Delete for good",
      text: "Every product, sale, expense, journal and staff link in this business is removed and cannot be brought back. People keep their sign-in accounts. Type the business name and your protected pages password to confirm.",
      fields: [{ name: "confirm_name", label: "Business name", required: true, placeholder: row.name },
        { name: "password", label: "Your protected pages password", type: "password", required: true }] });
    if (!values) return;
    if (values.confirm_name !== row.name.trim()) { await showError("The name does not match", `Type ${row.name} exactly as shown.`); return; }
    setBusy(true);
    try {
      await api(path, { method: "DELETE", body: JSON.stringify(values) });
      await showSuccess("Business deleted", `${row.name} and all its records were removed.`);
      onDeleted();
    } catch (e) {
      await showError("Could not delete the business", e.message);
      setBusy(false);
      if (["protected_unset", "protected_expired"].includes(e.data?.code)) setNeedsPassword((await api("/api/v1/auth/protected/")).protected);
    }
  };
  const submit = (handler) => (event) => { event.preventDefault(); void handler(Object.fromEntries(new FormData(event.currentTarget))); };
  const view = statusOf(row.subscription);
  const pricing = row.pricing;
  const priceOf = (code) => pricing?.plans.find((p) => p.plan === code);
  // Own prices typed here; a box left empty goes back to the price for the business's kind.
  const ownPrices = (values) => Object.fromEntries((pricing?.plans || []).map((p) => [p.plan, values[`price_${p.plan}`] ? values[`price_${p.plan}`] : null])
    .filter(([code, value]) => value !== (priceOf(code).source === "business" ? String(Number(priceOf(code).price)) : null)));
  return <article className="platformDetail" aria-label={`${row.name} subscription`}>
    <header><div><h2>{row.name}</h2><span className={`statusPill ${view.tone}`}>{view.label}</span>{!row.active && <span className="statusPill ended">Switched off</span>}</div>
      <button type="button" className="secondary" onClick={onClose}>Close</button></header>
    <dl>
      <div><dt>Owner</dt><dd>{row.owner.name || row.owner.username}</dd></div>
      <div><dt>Owner contacts</dt><dd>{[row.owner.phone, row.owner.email].filter(Boolean).join(" · ") || "—"}</dd></div>
      <div><dt>Business contacts</dt><dd>{[row.phone, row.email].filter(Boolean).join(" · ") || "—"}</dd></div>
      <div><dt>Kind of business</dt><dd>{row.business_type || "—"}</dd></div>
      <div><dt>Plan</dt><dd>{row.subscription.plan_name || "—"}</dd></div>
      <div><dt>Ends</dt><dd>{row.subscription.complimentary ? "Never" : dateText(row.subscription.ends_at)}</dd></div>
      <div><dt>Active users</dt><dd>{row.members}</dd></div>
      <div><dt>Paid in total</dt><dd>{money(row.total_paid)}</dd></div>
    </dl>

    {pricing && <>
      <h3>What it pays</h3>
      <ul className="platformPrices" aria-label="Prices for this business">{pricing.plans.map((p) => <li key={p.plan}>
        <strong>{p.plan_name}: {money(p.price, p.currency)}</strong> <small>{SOURCE[p.source]}{p.source === "business" ? ` · its kind pays ${money(p.kind_price, p.currency)}` : ""}{p.note ? ` · ${p.note}` : ""}</small>
      </li>)}</ul>
      {pricing.kind_changed && <p className="billingNote">The owner changed the kind of business to <b>{pricing.kind}</b>, but it is still billed as <b>{pricing.billing_kind}</b>.
        Bill it as {pricing.kind} if that is right; the price does not change until you do.</p>}
      <form onSubmit={submit((values) => change(`Bill it as ${kinds.find((k) => k.id === values.billing_sector)?.label}?`, "PATCH", values, "Its plans are now priced for that kind of business."))}>
        <label>Billed as<select name="billing_sector" defaultValue={pricing.billing_sector} key={pricing.billing_sector}>
          {!pricing.billing_sector && <option value="">Not set: standard prices</option>}<KindOptions kinds={kinds} /></select></label>
        <label>Note<TextBox name="note" maxLength={255} placeholder="Why (kept in the history)" /></label>
        <button disabled={busy}>Bill as this kind</button>
      </form>
      <form onSubmit={submit((values) => {
        const prices = ownPrices(values);
        if (!Object.keys(prices).length) return showError("Nothing changed", "Type a price, or clear one to go back to the price for its kind.");
        return change("Change what this business pays?", "PATCH", { prices, note: values.note }, "Its prices were updated. They apply to its next payment.");
      })}>
        {pricing.plans.map((p) => <label key={p.plan}>Own price for {p.plan_name} ({p.currency})
          <input name={`price_${p.plan}`} type="number" min="1" step="1" defaultValue={p.source === "business" ? Number(p.price) : ""} placeholder={`${Number(p.kind_price)} for its kind`} /></label>)}
        <label>Note<TextBox name="note" maxLength={255} placeholder="e.g. Agreed discount for the first year" /></label>
        <button disabled={busy}>Save its own prices</button>
      </form>
      <p className="muted">Leave a box empty for the price of its kind. New prices apply to its next payment.</p>
    </>}

    <h3>Change the subscription</h3>
    <form onSubmit={submit((values) => change("Change plan and status?", "PATCH", values, "The subscription was updated."))}>
      <label>Plan<select name="plan" defaultValue={row.subscription.plan || ""}>{plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select></label>
      <label>Status<select name="status" defaultValue={["TRIAL", "ACTIVE", "SUSPENDED", "CANCELLED"].includes(row.subscription.stored_status) ? row.subscription.stored_status : "ACTIVE"}>
        <option value="TRIAL">Free month</option><option value="ACTIVE">Active</option><option value="SUSPENDED">Suspended</option><option value="CANCELLED">Cancelled</option>
      </select></label>
      <label>Note<TextBox name="note" maxLength={255} placeholder="Why (kept in the history)" /></label>
      <button disabled={busy}>Apply</button>
    </form>
    <form onSubmit={submit((values) => change(`Add ${values.extend_days} days?`, "PATCH", { extend_days: Number(values.extend_days), note: values.note }, "The days were added."))}>
      <label>Add days<input name="extend_days" type="number" min="1" max="3650" defaultValue="30" required /></label>
      <label>Note<TextBox name="note" maxLength={255} placeholder="e.g. Compensation for downtime" /></label>
      <button disabled={busy}>Add days</button>
      <button type="button" className="secondary" disabled={busy} onClick={() => void change(row.subscription.complimentary ? "Stop the free platform plan?" : "Make this a free platform plan?", "PATCH",
        { complimentary: !row.subscription.complimentary }, row.subscription.complimentary ? "The business now needs a paid subscription." : "The business now has every feature for free.")}>
        {row.subscription.complimentary ? "Stop free plan" : "Make free (all features)"}</button>
    </form>

    <h3>Record a payment received outside the app</h3>
    <form onSubmit={submit((values) => change(`Record ${money(values.amount)} for ${values.plan}?`, "POST", values, "The payment was recorded and the subscription extended."))}>
      <label>Plan<select name="plan" defaultValue={row.subscription.plan || plans[0]?.code}
        onChange={(e) => { const amount = e.currentTarget.form.elements.amount; if (priceOf(e.target.value)) amount.value = Number(priceOf(e.target.value).price); }}>
        {plans.map((p) => <option key={p.code} value={p.code}>{p.name} · {money(priceOf(p.code)?.price ?? p.price, p.currency)}</option>)}</select></label>
      <label>Amount<input name="amount" type="number" min="1" step="0.01" required defaultValue={Number(priceOf(row.subscription.plan || plans[0]?.code)?.price ?? "") || ""} /></label>
      <label>Receipt / reference<TextBox name="receipt_number" maxLength={40} placeholder="M-Pesa code or cash receipt" /></label>
      <button disabled={busy}>Record payment</button>
    </form>

    <h3>Switch off or delete the business</h3>
    <p className="muted">{row.active
      ? "Switching off stops everyone in the business from opening it, straight away. Nothing is deleted and you can switch it back on at any time."
      : "The business is switched off: its people cannot open it. Switch it back on to restore access, or delete it for good."}</p>
    <div className="platformDanger">
      <button type="button" className={row.active ? "danger" : undefined} disabled={busy} onClick={() => void change(row.active ? "Switch this business off?" : "Switch this business back on?", "PATCH",
        { active: !row.active }, row.active ? "The business is switched off. Its people can no longer open it." : "The business is back on. Its people can open it again.")}>
        {row.active ? "Switch off business" : "Switch business back on"}</button>
      {!row.active && <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>Delete business for good</button>}
    </div>
    {needsPassword && <div className="platformProtected">
      <ProtectedPasswordForm state={needsPassword} onOpen={() => { setNeedsPassword(null); void remove(); }} />
      <button type="button" className="secondary" onClick={() => setNeedsPassword(null)}>Cancel</button>
    </div>}

    <h3>Payments</h3>
    {row.payments.length ? <table className="platformTable"><thead><tr><th>Date</th><th>Plan</th><th>Amount</th><th>Method</th><th>Status</th><th>Receipt</th><th>Paid until</th></tr></thead>
      <tbody>{row.payments.map((payment) => <tr key={payment.id}><td>{dateText(payment.created_at)}</td><td>{payment.plan}</td><td>{money(payment.amount, payment.currency)}</td>
        <td>{payment.method === "MPESA" ? `M-Pesa ${payment.phone}` : "Recorded"}</td>
        <td><span className={`paymentStatus ${payment.status.toLowerCase()}`}>{payment.status.toLowerCase()}</span>{payment.status !== "PAID" && <small>{payment.status_detail}</small>}</td>
        <td>{payment.receipt_number || "—"}</td><td>{dateText(payment.period_ends_at)}</td></tr>)}</tbody></table> : <p className="muted">No payments yet.</p>}
  </article>;
}

function PlanEditor({ plan, kinds, onSaved }) {
  const [modules, setModules] = useState(new Set(plan.enabled_modules));
  const [busy, setBusy] = useState(false);
  const kindPrices = plan.kind_prices || {};
  const save = async (event) => {
    event.preventDefault();
    const { name, price, description, active, ...typed } = Object.fromEntries(new FormData(event.currentTarget));
    const form = { name, price, description, active };
    // Only the kinds whose price changed; an emptied box goes back to the standard price.
    const kind_prices = Object.fromEntries(kinds.map((kind) => [kind.id, typed[`kind_${kind.id}`] || null])
      .filter(([id, value]) => value !== (kindPrices[id] ? String(Number(kindPrices[id])) : null)));
    if (!(await confirmAction({ title: `Save the ${plan.name} plan?`, text: "Changes apply to every business on this plan straight away. Prices apply to the next payment.", confirmButtonText: "Save plan" }))) return;
    setBusy(true);
    try {
      await api(`/api/v1/tenancy/platform-admin/plans/${plan.id}/`, { method: "PATCH", body: JSON.stringify({ ...form, active: form.active === "on", enabled_modules: [...modules], kind_prices }) });
      await onSaved();
      await showSuccess("Plan saved", `${form.name} is updated.`);
    } catch (e) {
      await showError("Could not save the plan", e.message);
    } finally {
      setBusy(false);
    }
  };
  const toggle = (id) => setModules((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  return <form onSubmit={(event) => void save(event)} aria-label={`${plan.name} plan`}>
    <h3>{plan.name} <small className="muted">({plan.code})</small></h3>
    <label>Name<TextBox name="name" defaultValue={plan.name} required maxLength={100} /></label>
    <label>Standard price ({plan.currency} per {plan.period_days} days)<input name="price" type="number" min="1" step="1" defaultValue={Number(plan.price)} required /></label>
    <details className="kindPrices">
      <summary>Price for each kind of business ({Object.keys(kindPrices).length} set{plan.business_prices ? ` · ${plan.business_prices} ${plan.business_prices === 1 ? "business has" : "businesses have"} its own` : ""})</summary>
      <p className="muted">Leave a box empty for the standard price.</p>
      {MODEL_ORDER.map((model) => <fieldset key={model}><legend>{MODEL_LABELS[model]}</legend>
        {kinds.filter((kind) => kind.model === model).map((kind) => <label key={kind.id}>{kind.label}{kind.listed ? "" : " (not listed)"}
          <input name={`kind_${kind.id}`} type="number" min="1" step="1" defaultValue={kindPrices[kind.id] ? Number(kindPrices[kind.id]) : ""} placeholder={String(Number(plan.price))} /></label>)}
      </fieldset>)}
    </details>
    <label>Description<TextBox name="description" defaultValue={plan.description} maxLength={255} /></label>
    <fieldset className="checkList"><legend>Tools included</legend>
      {Object.entries(MODULE_LABELS).map(([id, label]) => <label key={id}><input type="checkbox" checked={modules.has(id)} onChange={() => toggle(id)} /> {label}</label>)}
    </fieldset>
    <label className="inline"><input type="checkbox" name="active" defaultChecked={plan.active} /> Offered to businesses</label>
    <button disabled={busy}>{busy ? "Saving…" : "Save plan"}</button>
  </form>;
}

const KIND_STATUS = { SUGGESTED: { label: "Waiting for review", tone: "warn" }, LISTED: { label: "Listed", tone: "active" }, HIDDEN: { label: "Not listed", tone: "ended" } };

// Kinds of business owners created under "Other". Listing one adds it to the set-up list for every new owner.
export function BusinessKinds() {
  const [kinds, setKinds] = useState();
  const [error, setError] = useState("");
  const load = useCallback(() => api("/api/v1/tenancy/platform-admin/business-kinds/").then(setKinds).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  return <>
    <h2>Kinds of business added by owners</h2>
    <p className="muted">When an owner's business is not in the list, they name it under “Other”. List it here and the next owner finds it, with the tools and starter list the first one chose.</p>
    {error && !kinds && <ErrorState message={error} retry={load} />}
    {kinds && !kinds.length && <p className="muted">No owner has added a kind of business yet.</p>}
    {kinds && kinds.length > 0 && <div className="platformPlans">{kinds.map((kind) => <KindEditor key={`${kind.id}-${kind.status}`} kind={kind} onSaved={load} />)}</div>}
  </>;
}

function KindEditor({ kind, onSaved }) {
  const [modules, setModules] = useState(new Set(kind.modules));
  const [busy, setBusy] = useState(false);
  const status = KIND_STATUS[kind.status];
  const save = async (event, nextStatus) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget.form || event.currentTarget));
    const categories = String(form.categories || "").split(",").map((name) => name.trim()).filter(Boolean);
    setBusy(true);
    try {
      await api(`/api/v1/tenancy/platform-admin/business-kinds/${kind.id}/`, { method: "PATCH", body: JSON.stringify({
        label: form.label, hint: form.hint, keywords: form.keywords, modules: [...modules],
        ...(kind.business_model !== "SERVICES" ? { categories } : {}), ...(nextStatus ? { status: nextStatus } : {}) }) });
      await onSaved();
      await showSuccess(nextStatus === "LISTED" ? "Listed" : nextStatus === "HIDDEN" ? "Taken off the list" : "Saved",
        nextStatus === "LISTED" ? `New owners can now choose ${form.label}.` : `${form.label} is updated.`);
    } catch (e) {
      await showError("Could not save this kind of business", e.message);
    } finally {
      setBusy(false);
    }
  };
  const toggle = (id) => setModules((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  return <form onSubmit={(event) => void save(event)} aria-label={kind.label}>
    <h3>{kind.label} <span className={`statusPill ${status.tone}`}>{status.label}</span></h3>
    <p className="muted">{MODEL_LABELS[kind.business_model]} · {kind.uses} {kind.uses === 1 ? "business" : "businesses"} · first added by {kind.created_by || "a removed business"} on {dateText(kind.created_at)}</p>
    <label>Name<TextBox name="label" defaultValue={kind.label} required maxLength={100} /></label>
    <label>Short description<TextBox name="hint" defaultValue={kind.hint} maxLength={160} placeholder="What these businesses sell or do" /></label>
    <label>Search words<TextBox name="keywords" defaultValue={kind.keywords} maxLength={255} placeholder="Other names owners might search for" /></label>
    <fieldset className="checkList"><legend>Usual tools</legend>
      {kind.allowed_modules.map((id) => <label key={id}><input type="checkbox" checked={modules.has(id)} onChange={() => toggle(id)} /> {MODULE_LABELS[id]}</label>)}
    </fieldset>
    {kind.business_model !== "SERVICES" && <label>Product categories<TextBox name="categories" defaultValue={kind.categories.join(", ")} placeholder="Separate with commas" /></label>}
    {kind.business_model !== "GOODS" && <p className="muted">Starter services: {kind.services.map((service) => service.name).join(", ") || "none"}</p>}
    <div className="setupActions">
      <button type="submit" className="secondary" disabled={busy}>Save</button>
      {kind.status !== "LISTED" && <button type="button" disabled={busy} onClick={(event) => void save(event, "LISTED")}>List for everyone</button>}
      {kind.status !== "HIDDEN" && <button type="button" className="secondary" disabled={busy} onClick={(event) => void save(event, "HIDDEN")}>{kind.status === "LISTED" ? "Take off the list" : "Do not list"}</button>}
    </div>
  </form>;
}
