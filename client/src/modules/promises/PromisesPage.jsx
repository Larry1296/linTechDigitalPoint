import { useEffect, useRef, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { QUICK_PICKS, dueIn, forField, quickPick, telLink, when } from "./promiseTime";

const TAGS = { late: "Late", soon: "Due soon", later: "Open" };
const blank = () => ({ phone: "", customer_name: "", wanted: "", promised: "", due: forField(quickPick("tomorrow")) });
const fromPromise = (p) => ({ phone: p.phone, customer_name: p.customer_name, wanted: p.wanted, promised: p.promised, due: forField(new Date(p.due_at)) });
const toBody = (form) => ({ phone: form.phone, customer_name: form.customer_name, wanted: form.wanted, promised: form.promised,
  due_at: new Date(form.due).toISOString() });

// The customer, what they want, what they were promised and by when. The time it is written down is recorded by itself.
function PromiseForm({ start, saveLabel, onSave, onCancel, label }) {
  const [form, setForm] = useState(start);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const first = useRef(null);
  const set = (key) => (event) => setForm((all) => ({ ...all, [key]: event.target.value }));
  const submit = async (event) => {
    event.preventDefault();
    if (!form.due) { setError("Pick when you will answer them."); return; }
    setBusy(true); setError("");
    try {
      await onSave(toBody(form));
      if (!onCancel) { setForm(blank()); first.current?.focus(); }
    } catch (err) { setError(err.message); }
    setBusy(false);
  };
  return (
    <form className="promiseForm" onSubmit={(event) => void submit(event)} aria-label={label}
      onKeyDown={(event) => { if (event.key === "Escape" && onCancel) onCancel(); }}>
      <div className="promiseFields">
        <label>Customer's phone<input ref={first} type="tel" inputMode="tel" required maxLength={30} autoComplete="off" placeholder="0712 345 678"
          value={form.phone} onChange={set("phone")} autoFocus={Boolean(onCancel)} /></label>
        <label>Name <small className="muted">(if they gave it)</small><input maxLength={120} autoComplete="off" placeholder="e.g. Wanjiru"
          value={form.customer_name} onChange={set("customer_name")} /></label>
        <label className="promiseWide">What they are looking for<input required maxLength={300} autoComplete="off" placeholder="e.g. iPhone 13 screen protectors"
          value={form.wanted} onChange={set("wanted")} /></label>
        <label className="promiseWide">What you promised<input required maxLength={300} autoComplete="off" placeholder="e.g. Check with the supplier and call back"
          value={form.promised} onChange={set("promised")} /></label>
        <div className="promiseDue">
          <label>Answer them by<input type="datetime-local" required value={form.due} onChange={set("due")} /></label>
          <div className="promisePicks" role="group" aria-label="Quick times">
            {QUICK_PICKS.map(([kind, text]) => <button key={kind} type="button" className="secondary"
              onClick={() => setForm((all) => ({ ...all, due: forField(quickPick(kind)) }))}>{text}</button>)}
          </div>
        </div>
      </div>
      <div className="promiseFormButtons">
        <button disabled={busy}>{busy ? "Saving…" : saveLabel}</button>
        {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
      </div>
      <FormError title="Could not save the promise." message={error} />
    </form>
  );
}

function PromiseCard({ promise, canChange, canRemove, onClose, onReopen, onEdit, onRemove }) {
  const open = promise.status === "OPEN";
  const tag = open ? TAGS[promise.state] : promise.status === "MET" ? "Met" : "Not met";
  return (
    <li className={`promiseCard ${open ? promise.state : promise.status === "MET" ? "met" : "notMet"}`}>
      <div className="promiseTop">
        <span className="promiseTag">{tag}</span>
        <strong className="promiseWanted">{promise.wanted}</strong>
      </div>
      <p className="promisePromised"><span className="muted">You promised:</span> {promise.promised}</p>
      <p className="promiseWho">
        {promise.customer_name && <span>{promise.customer_name}</span>}
        <a href={telLink(promise.phone)} aria-label={`Call ${promise.customer_name || promise.phone}`}>{promise.phone}</a>
      </p>
      <dl className="promiseTimes">
        <div><dt>Answer by</dt><dd>{when(promise.due_at)}{open && <b> · {dueIn(promise.due_at)}</b>}</dd></div>
        <div><dt>Recorded</dt><dd>{when(promise.created_at)}{promise.created_by_name ? ` by ${promise.created_by_name}` : ""}</dd></div>
        {!open && <div><dt>Closed</dt><dd>{when(promise.closed_at)}{promise.outcome ? ` · ${promise.outcome}` : ""}</dd></div>}
      </dl>
      {(canChange || canRemove) && <div className="promiseActions">
        {canChange && open && <>
          <button type="button" onClick={() => onClose(promise, "MET")}>Met: they got it</button>
          <button type="button" className="secondary" onClick={() => onClose(promise, "NOT_MET")}>Not met</button>
          <button type="button" className="secondary" onClick={() => onEdit(promise)}>Change</button>
        </>}
        {canChange && !open && <button type="button" className="secondary" onClick={() => onReopen(promise)}>Open again</button>}
        {canRemove && <button type="button" className="secondary" onClick={() => onRemove(promise)}>Remove</button>}
      </div>}
    </li>
  );
}

// Promises made to customers who asked for something not in stock: call them back by the time promised. Only notes:
// they never change stock, money or the books. An open one is reminded in red on the dashboard as its time comes.
export function PromisesPage() {
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [problem, setProblem] = useState("");
  const [editing, setEditing] = useState(null);
  const [, tick] = useState(0);
  const load = async () => {
    try { setData(await api("/api/v1/promises/")); setError(""); } catch (err) { setError(err.message); }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load, { pollMs: 60000 });
  useEffect(() => { const timer = setInterval(() => tick((n) => n + 1), 60000); return () => clearInterval(timer); }, []);
  const act = async (path, options) => {
    setProblem("");
    try { setData(await api(path, options)); return true; } catch (err) { setProblem(err.message); return false; }
  };
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const close = async (promise, status) => {
    const answer = await askForm({
      title: status === "MET" ? "Promise met" : "Promise not met",
      text: `${promise.wanted}${promise.customer_name ? ` for ${promise.customer_name}` : ""}. It moves to the done list.`,
      fields: [{ name: "outcome", label: "What happened", placeholder: status === "MET" ? "e.g. Called, she came for two" : "e.g. Supplier has none, told him", value: "" }],
      confirmButtonText: status === "MET" ? "Mark as met" : "Mark as not met",
    });
    if (answer) await act(`/api/v1/promises/${promise.id}/`, { method: "PATCH", body: JSON.stringify({ status, outcome: answer.outcome }) });
  };
  const remove = async (promise) => {
    if (await confirmAction({ title: "Remove this promise?", text: `${promise.wanted} for ${promise.customer_name || promise.phone}. It is deleted, not kept as done.`, confirmButtonText: "Remove" }))
      await act(`/api/v1/promises/${promise.id}/`, { method: "DELETE" });
  };
  const canChange = can("core.change_customerpromise");
  const canRemove = can("core.delete_customerpromise");
  const card = (promise) => (editing === promise.id
    ? <li key={promise.id} className="promiseCard editing">
      <PromiseForm start={fromPromise(promise)} saveLabel="Save" label={`Change the promise for ${promise.wanted}`} onCancel={() => setEditing(null)}
        onSave={async (body) => { setData(await api(`/api/v1/promises/${promise.id}/`, { method: "PATCH", body: JSON.stringify(body) })); setEditing(null); }} />
    </li>
    : <PromiseCard key={promise.id} promise={promise} canChange={canChange} canRemove={canRemove} onClose={(p, s) => void close(p, s)}
      onReopen={(p) => void act(`/api/v1/promises/${p.id}/`, { method: "PATCH", body: JSON.stringify({ status: "OPEN" }) })}
      onEdit={(p) => setEditing(p.id)} onRemove={(p) => void remove(p)} />);
  return (
    <div className="promisesPage">
      <header className="promisesHead">
        <h1>Customer promises</h1>
        <p className="muted">When a customer asks for something you don't have and you promise to find out and call them back. Write it here so it
          is not forgotten: the dashboard shows it in red from {data.soon_hours} hours before the time you promised until you mark it met or not met.</p>
      </header>

      <dl className="promiseStats">
        <div className={data.late ? "late" : undefined}><dt>Late</dt><dd>{data.late}</dd></div>
        <div className={data.soon ? "soon" : undefined}><dt>Due within {data.soon_hours} hours</dt><dd>{data.soon}</dd></div>
        <div><dt>Open</dt><dd>{data.open.length}</dd></div>
        <div><dt>Met</dt><dd>{data.met}</dd></div>
        <div><dt>Not met</dt><dd>{data.not_met}</dd></div>
      </dl>

      {can("core.add_customerpromise") && <section className="promiseNew" aria-labelledby="promise-new">
        <h2 id="promise-new">New promise</h2>
        <PromiseForm start={blank()} saveLabel="Save the promise" label="New promise"
          onSave={async (body) => { setData(await api("/api/v1/promises/", { method: "POST", body: JSON.stringify(body) })); }} />
      </section>}
      <FormError title="Could not change the promise." message={problem} />

      <section aria-labelledby="promises-open">
        <h2 id="promises-open">Still to answer ({data.open.length})</h2>
        {data.open.length ? <ul className="promiseList">{data.open.map(card)}</ul>
          : <Empty>No promises waiting. When a customer asks for something you don't have, write it above.</Empty>}
      </section>
      {data.done.length > 0 && <section aria-labelledby="promises-done" className="promisesDone">
        <h2 id="promises-done">Done</h2>
        <ul className="promiseList">{data.done.map(card)}</ul>
      </section>}
    </div>
  );
}
