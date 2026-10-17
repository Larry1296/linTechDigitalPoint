import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { deleteCyberSale } from "./api";
import { label, PAYMENT_METHODS } from "../../core/ui/labels";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormField } from "../../components/forms/FormField";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { ReceiptPanel } from "../receipts/ReceiptPanel";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const UNITS = [["PER_PAGE", "page", "pages"], ["PER_COPY", "copy", "copies"], ["PER_SHEET", "sheet", "sheets"], ["PER_DOCUMENT", "document", "documents"],
  ["PER_HOUR", "hour", "hours"], ["PER_ITEM", "item", "items"], ["FIXED", "", "times"]];
const unit = (code) => UNITS.find(([value]) => value === code) || UNITS[UNITS.length - 1];
const per = (code) => (unit(code)[1] ? ` per ${unit(code)[1]}` : "");
const PERIODS = [["all", "Since the start"], ["month", "This month"], ["week", "This week"]];
const when = (value) => new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const cents = (value) => Math.round(Number(value || 0) * 100) / 100;

const OTHER = "other";
const NEW_SERVICE = "new-service";
// Every place a service can go, for a dropdown: main groups and "Group › Sub-group".
const groupChoices = (groups) => groups.flatMap((g) => [{ id: g.id, label: g.name }, ...g.subgroups.map((sub) => ({ id: sub.id, label: `${g.name} › ${sub.name}` }))]);
// Services in the order of their groups (then sub-groups), with services in no group last.
function byGroup(services, groups) {
  const sections = groups.map((g) => ({ key: String(g.id), name: g.name, parts: [
    { name: null, services: services.filter((s) => s.group?.id === g.id && !s.subgroup) },
    ...g.subgroups.map((sub) => ({ name: sub.name, services: services.filter((s) => s.subgroup?.id === sub.id) })),
  ].filter((part) => part.services.length) }));
  const other = services.filter((s) => !s.group);
  if (other.length) sections.push({ key: OTHER, name: "Other services", parts: [{ name: null, services: other }] });
  return sections.filter((section) => section.parts.length);
}

// How an option is priced, in plain words, for the person taking the money.
function priceRule(option) {
  if (option.price_varies) return Number(option.price) > 0 ? `Usually ${money(option.price)}${per(option.billing_unit)}; type what the customer paid` : "Type what the customer paid";
  if (Number(option.price) <= 0) return "No price set yet: type what the customer paid";
  if (Number(option.minimum_price) > 0) return `${money(option.price)}${per(option.billing_unit)}, can go down to ${money(option.minimum_price)}`;
  return `${money(option.price)}${per(option.billing_unit)}, fixed`;
}

function useLoad(path) {
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const load = async () => {
    try {
      setData(await api(path));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { setData(undefined); void load(); }, [path]);
  useLiveRefresh(load);
  return { data, setData, error, load };
}

function Totals({ totals, unitCode }) {
  return (
    <dl className="loanFigures">
      {PERIODS.map(([key, name]) => (
        <div key={key}>
          <dt>{name}</dt>
          <dd><strong>{money(totals[key]?.amount ?? totals[key])}</strong>
            {unitCode && <small> · {Number(totals[key].units).toLocaleString()} {unit(unitCode)[2]}</small>}</dd>
        </div>
      ))}
    </dl>
  );
}

// One line of a visit: what was done (group, service, price option), how many, and the amount charged for it.
const newLine = (serviceId = "") => ({ key: crypto.randomUUID(), groupId: "", serviceId, optionId: "", quantity: "1", typed: "" });

// Everything a line needs to show and check, worked out from what was picked.
function lineState(line, services, fixedService, isManager) {
  const service = fixedService || services.find((s) => String(s.id) === line.serviceId);
  const options = (service?.options || []).filter((o) => o.active);
  const option = options.find((o) => String(o.id) === line.optionId) || options[0];
  const listed = option ? cents(Number(line.quantity || 0) * Number(option.price)) : 0;
  const mustType = Boolean(option && (option.price_varies || Number(option.price) <= 0));
  const canEdit = Boolean(option && (mustType || isManager || Number(option.minimum_price) > 0));
  const total = line.typed !== "" ? Number(line.typed) : mustType ? 0 : listed;
  const lowest = option && Number(option.minimum_price) > 0 ? cents(Number(line.quantity || 0) * Number(option.minimum_price)) : null;
  const checked = option && !isManager && !mustType && line.typed !== "";
  const tooLow = Boolean(checked && (lowest === null ? total < listed : total < lowest));
  const tooHigh = Boolean(checked && total > listed);
  const ready = Boolean(option && Number(line.quantity) > 0 && total > 0 && !tooLow && !tooHigh);
  return { service, options, option, listed, mustType, canEdit, total, lowest, tooLow, tooHigh, ready };
}

function IncomeLine({ line, state, sections, fixedService, number, onChange, onRemove, onAddService, onEditService }) {
  const { options, option, listed, mustType, canEdit, total, lowest, tooLow, tooHigh } = state;
  const id = (name) => `${name}-${line.key}`;
  return (
    <fieldset className="incomeLine">
      <legend>{fixedService ? "What was done" : `Service ${number}`}</legend>
      {!fixedService && (
        // Every service in one list (under its group when there are groups); the last choice creates a new one.
        <FormField label="Service">
          <select value={line.serviceId} required onChange={(event) => (event.target.value === NEW_SERVICE ? onAddService?.()
            : onChange({ serviceId: event.target.value, optionId: "", typed: "", quantity: "1" }))}>
            <option value="" disabled>Choose the service done</option>
            {sections.map((section) => {
              const options = section.parts.flatMap((part) => part.services.map((s) => (
                <option key={s.id} value={s.id}>{part.name ? `${part.name} › ` : ""}{s.name}</option>)));
              return sections.length > 1 ? <optgroup key={section.key} label={section.name}>{options}</optgroup> : options;
            })}
            {onAddService && <option value={NEW_SERVICE}>+ Create a new service…</option>}
          </select>
        </FormField>
      )}
      {!fixedService && onEditService && state.service && (
        <div className="actionRow serviceManage">
          <button type="button" className="linkButton" onClick={() => onEditService(state.service.id)}>Edit {state.service.name}: name, group or prices</button>
        </div>
      )}
      {options.length > 1 && (
        <FormField label="Price option">
          <select value={String(option?.id || "")} onChange={(event) => onChange({ optionId: event.target.value, typed: "" })}>
            {options.map((o) => <option key={o.id} value={o.id}>{o.name} · {o.price_varies || Number(o.price) <= 0 ? "amount varies" : `${money(o.price)}${per(o.billing_unit)}`}</option>)}
          </select>
        </FormField>
      )}
      {option && (
        <>
          <FormField label={`How many ${unit(option.billing_unit)[2]}`} type="number" min="0.001" step="any" required value={line.quantity}
            onChange={(event) => onChange({ quantity: event.target.value, ...(mustType ? {} : { typed: "" }) })} />
          <FormField label={`Amount charged (${businessCurrency()})`} type="number" min="0.01" step="0.01" required inputMode="decimal"
            value={line.typed !== "" ? line.typed : mustType ? "" : listed} readOnly={!canEdit} placeholder={mustType ? "Type the amount" : undefined}
            onChange={(event) => onChange({ typed: event.target.value })} aria-describedby={id("rule")} />
          <p id={id("rule")} className={tooLow || tooHigh ? "formNotice" : "muted"}>
            {tooLow ? (lowest === null ? `This price is fixed at ${money(listed)}. A different amount needs a manager.` : `The lowest for this is ${money(lowest)}.`)
              : tooHigh ? `The price for this is ${money(listed)}. Charging more needs a manager.` : priceRule(option)}
            {total > 0 && !tooLow && !tooHigh && Number(line.quantity) > 1 && ` · ${money(total)} in all`}
          </p>
        </>
      )}
      {onRemove && <button type="button" className="linkButton" onClick={onRemove}>Remove this service</button>}
    </fieldset>
  );
}

/** One customer's visit: each service done (group, service, price option, how many, amount charged), then one payment
 * and one receipt for the lot. On a service's own page the service is already chosen. */
export function RecordIncome({ services, groups = [], fixedService, onSaved, onServicesChanged, title = "Record income" }) {
  const { user } = useAuth();
  const can = (p) => Boolean(user?.permissions?.includes(p));
  const canRecord = can("cyber.add_cyberjob") && can("cyber.complete_cyber_job");
  const isManager = can("cyber.change_cyberjobline");
  const canAddService = !fixedService && Boolean(onServicesChanged) && can("cyber.add_cyberserviceprofile") && can("catalog.add_product");
  const canEditService = !fixedService && Boolean(onServicesChanged) && can("cyber.change_cyberserviceprofile") && can("catalog.change_product");
  // Adding or editing a service from a line's dropdowns: { lineKey, serviceId } (no serviceId when adding).
  const [managing, setManaging] = useState(null);
  const panel = useRef(null);
  useEffect(() => { if (managing) panel.current?.scrollIntoView?.({ block: "nearest" }); }, [managing]);
  const offered = services.filter((s) => s.active && s.options.some((o) => o.active));
  const sections = byGroup(offered, groups);
  const [lines, setLines] = useState(() => [newLine(fixedService ? String(fixedService.id) : "")]);
  const [method, setMethod] = useState("CASH");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  if (!canRecord) return null;
  if (!offered.length && !fixedService) return <Empty>Add your services first (below), then record what they earn here.</Empty>;
  const states = lines.map((line) => lineState(line, offered, fixedService, isManager));
  const total = cents(states.reduce((sum, state) => sum + (state.ready ? state.total : 0), 0));
  const ready = states.every((state) => state.ready);
  const change = (key, values) => setLines((rows) => rows.map((row) => (row.key === key ? { ...row, ...values } : row)));
  const describe = (state, line) => `${state.service.name}${state.options.length > 1 ? ` (${state.option.name})` : ""}${Number(line.quantity) !== 1 ? ` × ${Number(line.quantity)}` : ""}`;
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    const items = lines.map((line, index) => `${describe(states[index], line)}: ${money(states[index].total)}`);
    if (!(await confirmAction({ title: `Record ${money(total)}${lines.length > 1 ? ` for ${lines.length} services` : ""}?`,
      text: `${items.join("\n")}\n\nPaid by ${label(method)}, one receipt.`, confirmButtonText: "Record income" }))) return;
    const payload = lines.map((line, index) => {
      const state = states[index];
      return { option_id: state.option.id, quantity: line.quantity, ...(state.mustType || cents(state.total) !== state.listed ? { amount: String(cents(state.total)) } : {}) };
    });
    const payment = { payment_method: method, payment_reference: values.payment_reference || "", customer_name: values.customer_name || "", idempotency_key: crypto.randomUUID() };
    setBusy(true);
    setError("");
    setDone("");
    try {
      const result = fixedService
        ? await api(`/api/v1/cyber/income/${fixedService.id}/`, { method: "POST", body: JSON.stringify({ ...payload[0], ...payment }) })
        : await api("/api/v1/cyber/income/record/", { method: "POST", body: JSON.stringify({ lines: payload, ...payment }) });
      setDone(`${money(total)} recorded${lines.length > 1 ? ` for ${lines.length} services on one receipt` : ""}.${method === "MPESA" ? " The M-Pesa payment waits for confirmation under Sales." : ""}`);
      form.reset();
      setLines([newLine(fixedService ? String(fixedService.id) : "")]);
      setMethod("CASH");
      await onSaved(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const editing = managing?.serviceId ? services.find((s) => s.id === managing.serviceId) : null;
  const managingLine = lines.find((line) => line.key === managing?.lineKey);
  // A new service is picked on the line it was added from, ready to record.
  const added = async (saved) => {
    await onServicesChanged();
    if (managingLine) change(managingLine.key, { groupId: saved.group ? String(saved.group.id) : OTHER, serviceId: String(saved.id), optionId: "", typed: "", quantity: "1" });
    setManaging(null);
  };
  const managePanel = managing && (
    <div ref={panel} className="serviceManagePanel">
      {editing ? (
        <section className="formCard" aria-label={`Edit ${editing.name}`}>
          <h2>Edit {editing.name}</h2>
          <ServiceDetails service={{ ...editing, groups }} onSaved={() => onServicesChanged()} startOpen />
          <PriceOptions service={editing} onSaved={() => onServicesChanged()} />
          <div className="actionRow"><button type="button" className="secondary" onClick={() => setManaging(null)}>Done</button></div>
        </section>
      ) : (
        <NewService groups={groups} startOpen defaultGroup={managingLine && managingLine.groupId !== OTHER ? managingLine.groupId : ""}
          onSaved={added} onCancel={() => setManaging(null)} />
      )}
    </div>
  );
  return (
    <>
    <form className="formCard incomeEntry" onSubmit={(event) => void submit(event)} aria-label="Record income">
      <h2>{title}</h2>
      {!fixedService && <p className="muted">For a customer already served: choose each thing they had done, then how they paid. It all goes on one receipt.</p>}
      <div className="incomeLines" aria-busy={busy}>
        {lines.map((line, index) => (
          <IncomeLine key={line.key} line={line} state={states[index]} sections={sections} fixedService={fixedService} number={index + 1}
            onChange={(values) => change(line.key, values)} onRemove={lines.length > 1 ? () => setLines((rows) => rows.filter((row) => row.key !== line.key)) : null}
            onAddService={canAddService ? () => setManaging({ lineKey: line.key }) : null}
            onEditService={canEditService ? (serviceId) => setManaging({ lineKey: line.key, serviceId }) : null} />
        ))}
      </div>
      {!fixedService && <button type="button" className="secondary" disabled={busy} onClick={() => setLines((rows) => [...rows, newLine()])}>+ Another item for this customer</button>}
      {lines.length > 1 && (
        <ul className="incomeSummary" aria-label="This visit">
          {lines.map((line, index) => states[index].ready && <li key={line.key}><span>{describe(states[index], line)}</span><span>{money(states[index].total)}</span></li>)}
          <li className="incomeSummaryTotal"><span>Total</span><span>{money(total)}</span></li>
        </ul>
      )}
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Paid by">
          <select value={method} onChange={(event) => setMethod(event.target.value)}>
            {PAYMENT_METHODS.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </FormField>
        <FormField label={method === "MPESA" ? "M-Pesa code" : "Reference (optional)"} name="payment_reference" maxLength={120} required={method === "MPESA"} autoComplete="off" />
        <FormField label="Customer or note (optional)" name="customer_name" maxLength={160} autoComplete="off" placeholder="e.g. Mary, KRA returns for John" />
      </fieldset>
      <button disabled={busy || !ready}>{busy ? "Recording…" : ready ? `Record ${money(total)}` : "Record income"}</button>
      <FormError title="Could not record the income." message={error} />
      {done && <FormSuccess message={done} />}
    </form>
    {managePanel}
    </>
  );
}

function GroupSelect({ groups, value }) {
  return (
    <FormField label="Group">
      <select name="category_id" defaultValue={value ? String(value) : ""}>
        <option value="">No group</option>
        {groupChoices(groups).map((choice) => <option key={choice.id} value={choice.id}>{choice.label}</option>)}
      </select>
    </FormField>
  );
}

function OptionFields({ option, canSeeCost }) {
  const [varies, setVaries] = useState(Boolean(option?.price_varies));
  return (
    <>
      <FormField label="Option name" name="name" required maxLength={120} defaultValue={option?.name} placeholder="e.g. Single side, Both sides, Bulk 50+ pages" />
      <FormField label="Charged">
        <select name="billing_unit" defaultValue={option?.billing_unit || "PER_PAGE"}>
          {UNITS.map(([value, one]) => <option key={value} value={value}>{one ? `Per ${one}` : "Fixed price (per job)"}</option>)}
        </select>
      </FormField>
      <FormField label={`${varies ? "Usual price (optional)" : "Price"} (${businessCurrency()})`} name="price" type="number" min="0" step="0.01" required={!varies}
        defaultValue={option && option.price !== "" ? Number(option.price) : ""} />
      <label className="checkLabel"><input type="checkbox" name="price_varies" checked={varies} onChange={(event) => setVaries(event.target.checked)} />
        The amount varies: staff type what the customer paid</label>
      {!varies && <FormField label={`Lowest price staff may accept (${businessCurrency()}, optional)`} name="minimum_price" type="number" min="0" step="0.01"
        defaultValue={option && Number(option.minimum_price) ? Number(option.minimum_price) : ""} placeholder="Leave empty for a fixed price" />}
      {canSeeCost && <FormField label={`Your cost per unit, e.g. paper and ink (${businessCurrency()}, optional)`} name="cost" type="number" min="0" step="0.01"
        defaultValue={option?.cost && Number(option.cost) ? Number(option.cost) : ""} />}
      {option?.id && <label className="checkLabel"><input type="checkbox" name="active" defaultChecked={option.active} /> In use (untick to hide this option)</label>}
    </>
  );
}

const optionBody = (form, isNew) => {
  const values = Object.fromEntries(new FormData(form));
  return { name: values.name, billing_unit: values.billing_unit, price: values.price || "0", price_varies: values.price_varies === "on",
    minimum_price: values.minimum_price || "0", ...(values.cost !== undefined && values.cost !== "" ? { cost: values.cost } : {}),
    active: isNew ? true : values.active === "on" };
};

/** Each price option of a service: its name, unit, price rule, cost and whether it is in use. */
function PriceOptions({ service, onSaved }) {
  const { user } = useAuth();
  const can = (p) => Boolean(user?.permissions?.includes(p));
  const canEdit = can("cyber.change_cyberserviceprofile") && can("catalog.change_productvariant");
  const canAdd = can("cyber.add_cyberserviceprofile") && can("catalog.add_productvariant");
  const canSeeCost = can("accounting.view_profit");
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (event, path, isNew) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await api(path, { method: "POST", body: JSON.stringify(optionBody(event.currentTarget, isNew)) }));
      setEditing(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-labelledby="price-options">
      <h2 id="price-options">Price options</h2>
      <p className="muted">Give this service as many prices as you need, e.g. single side, both sides, bulk, express. Each can be fixed, allow bargaining
        down to a lowest price, or let staff type the amount.</p>
      <table className="incomeTable">
        <thead><tr><th>Option</th><th>Price</th><th>This month</th><th><span className="visuallyHidden">Action</span></th></tr></thead>
        <tbody>{service.options.map((o) => (
          <tr key={o.id} className={o.active ? undefined : "muted"}>
            <td>{o.name}{!o.active && <small> · hidden</small>}</td>
            <td>{priceRule(o)}{canSeeCost && Number(o.cost) > 0 && <small className="muted"> · costs you {money(o.cost)}{per(o.billing_unit)}</small>}</td>
            <td>{money(o.month.amount)}<small className="muted"> · {Number(o.month.units).toLocaleString()} {unit(o.billing_unit)[2]}</small></td>
            <td>{canEdit && <button type="button" className="secondary" onClick={() => setEditing(o.id)} aria-label={`Edit ${o.name}`}>Edit</button>}</td>
          </tr>
        ))}</tbody>
      </table>
      {editing && editing !== "new" && (
        <form className="formCard" onSubmit={(event) => void save(event, `/api/v1/cyber/income/options/${editing}/`, false)} aria-label="Edit price option">
          <h3>Edit price option</h3>
          <fieldset disabled={busy} className="loanFields"><OptionFields key={editing} option={service.options.find((o) => o.id === editing)} canSeeCost={canSeeCost} /></fieldset>
          <div className="actionRow"><button disabled={busy}>Save option</button><button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button></div>
        </form>
      )}
      {editing === "new" && (
        <form className="formCard" onSubmit={(event) => void save(event, `/api/v1/cyber/income/${service.id}/options/`, true)} aria-label="Add price option">
          <h3>Add a price option</h3>
          <fieldset disabled={busy} className="loanFields"><OptionFields canSeeCost={canSeeCost} /></fieldset>
          <div className="actionRow"><button disabled={busy}>Add option</button><button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button></div>
        </form>
      )}
      {canAdd && !editing && <button type="button" onClick={() => setEditing("new")}>Add a price option</button>}
      <FormError title="Could not save the price option." message={error} />
    </section>
  );
}

export function NewService({ groups, onSaved, startOpen = false, defaultGroup = "", onCancel }) {
  const [open, setOpen] = useState(startOpen);
  const close = () => { setOpen(false); onCancel?.(); };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    setBusy(true);
    setError("");
    try {
      const saved = await api("/api/v1/cyber/income/", { method: "POST", body: JSON.stringify({ ...optionBody(form, true), option_name: values.name,
        name: values.service_name, notes: values.notes || "", category_id: values.category_id ? Number(values.category_id) : null }) });
      if (!startOpen) setOpen(false);
      await onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  if (!open) return <button type="button" className="secondary" onClick={() => setOpen(true)}>+ Create a new service</button>;
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="Create a new service">
      <h2>Create a new service</h2>
      <p className="muted">A service you offer, with its price. This does not record a sale.</p>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Service name" name="service_name" required maxLength={160} placeholder="e.g. Binding" />
        <GroupSelect groups={groups} value={defaultGroup} />
        <OptionFields option={{ name: "Standard", billing_unit: "FIXED", price: "", minimum_price: "0", price_varies: false }} canSeeCost={false} />
        <FormField label="Note (optional)" name="notes" maxLength={240} placeholder="e.g. government fees are separate" />
      </fieldset>
      <p className="muted">You can add more price options to it afterwards.</p>
      <div className="actionRow"><button disabled={busy}>Create service</button><button type="button" className="secondary" onClick={close}>Cancel</button></div>
      <FormError title="Could not create the service." message={error} />
    </form>
  );
}

function NewGroup({ groups, onSaved }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/cyber/income/groups/", { method: "POST", body: JSON.stringify({ name: values.name, parent_id: values.parent_id ? Number(values.parent_id) : null }) });
      setOpen(false);
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  if (!open) return <button type="button" className="secondary" onClick={() => setOpen(true)}>Add a group</button>;
  return (
    <form className="formCard" onSubmit={(event) => void submit(event)} aria-label="Add a group">
      <h2>Add a group</h2>
      <fieldset disabled={busy} className="loanFields">
        <FormField label="Group name" name="name" required maxLength={120} placeholder="e.g. Design & Branding" />
        <FormField label="Inside">
          <select name="parent_id" defaultValue="">
            <option value="">Nothing: a main group</option>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name} (as a sub-group)</option>)}
          </select>
        </FormField>
      </fieldset>
      <div className="actionRow"><button disabled={busy}>Add group</button><button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button></div>
      <FormError title="Could not add the group." message={error} />
    </form>
  );
}

function ServiceDetails({ service, onSaved, startOpen = false }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true);
    setError("");
    try {
      onSaved(await api(`/api/v1/cyber/income/${service.id}/settings/`, { method: "POST", body: JSON.stringify({
        name: values.name, notes: values.notes || "", category_id: values.category_id ? Number(values.category_id) : null }) }));
      event.target.closest("details")?.removeAttribute("open");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="serviceDetails" open={startOpen || undefined}>
      <summary>Change name, group or note</summary>
      <form onSubmit={(event) => void submit(event)} aria-label="Service details">
        <fieldset disabled={busy} className="loanFields">
          <FormField label="Service name" name="name" required maxLength={160} defaultValue={service.name} />
          <GroupSelect groups={service.groups} value={service.subgroup?.id || service.group?.id} />
          <FormField label="Note (optional)" name="notes" maxLength={240} defaultValue={service.notes} />
        </fieldset>
        <button disabled={busy}>Save</button>
        <FormError title="Could not save the service." message={error} />
      </form>
    </details>
  );
}

/** All services: record income from a service dropdown, see each service's revenue, and open a service as a full page. */
export function CyberIncomePage() {
  const { user } = useAuth();
  const canAdd = ["cyber.add_cyberserviceprofile", "catalog.add_product"].every((p) => user?.permissions?.includes(p));
  const canAddGroup = Boolean(user?.permissions?.includes("catalog.add_category"));
  const { data, error, load } = useLoad("/api/v1/cyber/income/");
  const [search, setSearch] = useState("");
  const shown = useMemo(() => (data?.services || []).filter((s) => s.name.toLowerCase().includes(search.trim().toLowerCase())), [data, search]);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  return (
    <>
      <span className="eyebrow">Cyber Services</span>
      <h1>Income by service</h1>
      <Totals totals={data.totals} />
      <RecordIncome services={data.services} groups={data.groups} onSaved={load} onServicesChanged={load} />
      <section aria-labelledby="revenue-heading">
        <div className="saleHeading">
          <h2 id="revenue-heading">Revenue by service</h2>
          <div className="actionRow">{canAddGroup && <NewGroup groups={data.groups} onSaved={load} />}{canAdd && <NewService groups={data.groups} onSaved={load} />}</div>
        </div>
        {data.services.length > 8 && <label className="incomeSearch">Find a service<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="e.g. KRA, lamination" maxLength={60} /></label>}
        {!data.services.length ? <Empty>No services yet. Add the services you offer (printing, photocopy, typing…).</Empty>
          : !shown.length ? <Empty>No service matches “{search}”.</Empty> : (
            <table className="incomeTable">
              <thead><tr><th>Service</th>{PERIODS.map(([key, name]) => <th key={key}>{name}</th>)}</tr></thead>
              {byGroup(shown, data.groups).map((section) => {
                const all = section.parts.flatMap((part) => part.services);
                return (
                  <tbody key={section.key} className="incomeGroup">
                    <tr className="incomeGroupHead">
                      <th scope="rowgroup">{section.name}</th>
                      {PERIODS.map(([key]) => <td key={key}>{money(all.reduce((sum, s) => sum + Number(s[key].amount), 0))}</td>)}
                    </tr>
                    {section.parts.map((part) => [
                      part.name && <tr key={`${section.key}-${part.name}`} className="incomeSubHead"><th colSpan={PERIODS.length + 1} scope="rowgroup">{part.name}</th></tr>,
                      ...part.services.map((s) => (
                        <tr key={s.id} className={s.active ? undefined : "muted"}>
                          <td><Link to={`/admin/cyber/income/${s.id}`}>{s.name}</Link>
                            <small className="muted">{s.options.length > 1 ? `${s.options.filter((o) => o.active).length} price options` : priceRule(s.options[0])}</small></td>
                          {PERIODS.map(([key]) => <td key={key}>{money(s[key].amount)}{s[key].times > 0 && <small className="muted"> · {s[key].times} {s[key].times === 1 ? "sale" : "sales"}</small>}</td>)}
                        </tr>
                      )),
                    ])}
                  </tbody>
                );
              })}
            </table>
          )}
      </section>
    </>
  );
}

// Deletes the service after asking. The server erases one never used; one with income is removed from every list
// and can no longer be sold, while its past income stays in the totals and the books.
function DeleteService({ service, onDeleted }) {
  const [error, setError] = useState("");
  const used = service.history.length > 0;
  const remove = async () => {
    if (!(await confirmAction({ title: `Delete ${service.name}?`, confirmButtonText: "Delete service",
      text: used ? "It disappears from your services and can no longer be sold. Its past income and receipts are kept."
        : "It is removed permanently with its price options." }))) return;
    setError("");
    try {
      onDeleted(await api(`/api/v1/cyber/income/${service.id}/delete/`, { method: "POST" }));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <>
      <button type="button" className="danger" onClick={() => void remove()}>Delete service</button>
      <FormError title="Could not delete the service." message={error} />
    </>
  );
}

/** One service as a full page: its revenue, quick entry, price options and history. */
export function CyberServiceIncomePage() {
  const { serviceId } = useParams();
  const { user } = useAuth();
  const canEditService = ["cyber.change_cyberserviceprofile", "catalog.change_product"].every((p) => user?.permissions?.includes(p));
  const canDelete = Boolean(user?.permissions?.includes("cyber.delete_cyberserviceprofile"));
  const canDeleteSales = Boolean(user?.permissions?.includes("commerce.change_sale"));
  const [deleteError, setDeleteError] = useState("");
  // A payment recorded wrongly: its whole receipt is deleted, out of that day's figures, then it can be recorded again.
  const removeSale = async (row) => {
    const values = await askForm({ title: `Delete receipt ${row.receipt_number}?`, confirmButtonText: "Delete",
      text: "Use this when it was recorded wrongly. Everything on this receipt and its payment come out of that day's figures and disappear from the desk, sales and income. Record it again correctly afterwards.",
      fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. recorded wrongly, will record again" }] });
    if (!values) return;
    setDeleteError("");
    try {
      await deleteCyberSale(row.sale_id, values.reason);
      await load();
    } catch (err) {
      setDeleteError(err.message);
    }
  };
  const navigate = useNavigate();
  const { data, setData, error, load } = useLoad(`/api/v1/cyber/income/${serviceId}/`);
  const [receipt, setReceipt] = useState(null);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const single = data.options.length === 1 ? data.options[0].billing_unit : null;
  return (
    <>
      <span className="eyebrow"><Link to="/admin/cyber/income">Income by service</Link></span>
      <h1>{data.name}</h1>
      <p className="muted">{[data.group ? [data.group.name, data.subgroup?.name].filter(Boolean).join(" › ") : "No group", data.notes].filter(Boolean).join(" · ")}</p>
      {canEditService && <ServiceDetails service={data} onSaved={(saved) => setData(saved)} />}
      {canDelete && <DeleteService service={data} onDeleted={() => navigate("/admin/cyber/income")} />}
      <Totals totals={data} unitCode={single} />
      <RecordIncome key={data.id} services={[data]} fixedService={data} onSaved={(saved) => setData(saved)} />
      <PriceOptions service={data} onSaved={(saved) => setData(saved)} />
      <section aria-labelledby="income-history">
        <h2 id="income-history">History</h2>
        <FormError title="Could not delete the receipt." message={deleteError} />
        {!data.history.length ? <Empty>Nothing recorded for {data.name} yet.</Empty> : (
          <table className="incomeTable">
            <thead><tr><th>When</th><th>Option</th><th>How many</th><th>Amount</th><th>Paid by</th><th>Customer</th><th>Receipt</th>{canDeleteSales && <th><span className="visuallyHidden">Delete</span></th>}</tr></thead>
            <tbody>{data.history.map((row) => (
              <tr key={row.id}>
                <td>{when(row.date)}</td>
                <td>{row.option}</td>
                <td>{Number(row.quantity).toLocaleString()}</td>
                <td>{money(row.amount)}</td>
                <td>{label(row.payment_method) || "—"}</td>
                <td>{row.customer || "—"}</td>
                <td><button type="button" className="linkButton" onClick={() => setReceipt(row.sale_id)}>{row.receipt_number}</button></td>
                {canDeleteSales && <td><button type="button" className="danger" aria-label={`Delete ${row.receipt_number}`} onClick={() => void removeSale(row)}>Delete</button></td>}
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>
      {receipt && <ReceiptPanel saleId={receipt} onClose={() => setReceipt(null)} />}
    </>
  );
}
