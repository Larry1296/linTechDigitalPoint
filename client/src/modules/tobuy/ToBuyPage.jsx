import { useEffect, useRef, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const label = (v) => (!v.variant_name || v.variant_name === "Standard" ? v.product_name : `${v.product_name} ${v.variant_name}`);
const num = (value) => (value === "" || value == null ? null : Number(value));
const lineTotal = (count, price) => (num(price) == null || !num(count) ? null : num(count) * num(price));
const plain = (value) => String(Number(value));
const HAVE_KEY = "lintech.toBuy.have";
const readHave = () => { try { return localStorage.getItem(HAVE_KEY) || ""; } catch { return ""; } };
const keepHave = (value) => { try { localStorage.setItem(HAVE_KEY, value); } catch { /* this device only, and only if allowed */ } };

// Your products as you type, so a line can be linked to the one it is: it then leaves the list when that is received.
function useProductSuggestions(text, enabled) {
  const [found, setFound] = useState([]);
  useEffect(() => {
    const q = text.trim();
    if (!enabled || q.length < 2) { setFound([]); return undefined; }
    let live = true;
    const timer = setTimeout(() => {
      api(`/api/v1/inventory/variants/search/?q=${encodeURIComponent(q)}`).then((rows) => { if (live) setFound(Array.isArray(rows) ? rows.slice(0, 8) : []); })
        .catch(() => { if (live) setFound([]); });
    }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [text, enabled]);
  return found;
}

// An item: what, how many of what, at what price each; its total is worked out as you type.
function AddItem({ canSearch, onAdded }) {
  const [name, setName] = useState("");
  const [variant, setVariant] = useState(null);
  const [count, setCount] = useState("1");
  const [unit, setUnit] = useState("");
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const first = useRef(null);
  const found = useProductSuggestions(variant ? "" : name, canSearch);
  const total = lineTotal(count, price);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onAdded({ name, variant: variant?.id ?? null, count: count || "1", unit, unit_price: price === "" ? null : price, note });
      setName(""); setVariant(null); setCount("1"); setUnit(""); setPrice(""); setNote("");
      first.current?.focus();
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };
  return (
    <form className="toBuyAdd" onSubmit={(event) => void submit(event)} aria-label="Add to the list">
      <div className="toBuyFields">
        <label className="toBuyName">Item
          <input ref={first} value={name} required maxLength={160} autoComplete="off" placeholder="e.g. Type-C cables" list="to-buy-products"
            onChange={(event) => {
              const typed = event.target.value;
              const match = found.find((v) => label(v) === typed);
              setName(typed);
              setVariant(match ? { id: match.id, label: label(match) } : null);
            }} />
        </label>
        <datalist id="to-buy-products">{found.map((v) => <option key={v.id} value={label(v)}>{v.category}</option>)}</datalist>
        <label>How many<input type="number" min="0.001" step="any" inputMode="decimal" required value={count} onChange={(event) => setCount(event.target.value)} /></label>
        <label>Unit<input value={unit} maxLength={30} autoComplete="off" placeholder="pcs, cartons" onChange={(event) => setUnit(event.target.value)} /></label>
        <label>Price each ({businessCurrency()})<input type="number" min="0" step="0.01" inputMode="decimal" value={price} placeholder="If you know it"
          onChange={(event) => setPrice(event.target.value)} /></label>
        <div className="toBuyLineTotal" aria-live="polite"><span>Total</span><strong>{total == null ? "—" : money(total)}</strong></div>
        <button disabled={busy || !name.trim()}>Add</button>
        <label className="toBuyNote">Note<input value={note} maxLength={200} autoComplete="off" placeholder="e.g. from the Luthuli supplier" onChange={(event) => setNote(event.target.value)} /></label>
      </div>
      <p className="muted toBuyHint">{variant ? `Linked to your product ${variant.label}: it leaves the list when you receive it into stock.`
        : "Pick one of your products from the suggestions to link it, or type anything new: it leaves the list when you receive a product of that name."}</p>
      <FormError title="Could not add it." message={error} />
    </form>
  );
}

// The whole line changed at once: what it is, how many of what, the price each and the note. Works on bought lines too.
function EditItem({ item, canSearch, onSave, onCancel }) {
  const [name, setName] = useState(item.name);
  const [variant, setVariant] = useState(item.variant ? { id: item.variant, label: item.product } : null);
  const [count, setCount] = useState(plain(item.count));
  const [unit, setUnit] = useState(item.unit || "");
  const [price, setPrice] = useState(item.unit_price == null ? "" : plain(item.unit_price));
  const [note, setNote] = useState(item.note || "");
  const [busy, setBusy] = useState(false);
  const found = useProductSuggestions(variant && name === item.name ? "" : name, canSearch);
  const total = lineTotal(count, price);
  const listId = `to-buy-edit-${item.id}`;
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    const done = await onSave(item, { name, variant: variant?.id ?? null, count: count || "1", unit, unit_price: price === "" ? null : price, note });
    if (!done) setBusy(false);
  };
  return (
    <li className="toBuyEditing">
      <form className="toBuyFields" onSubmit={(event) => void submit(event)} onKeyDown={(event) => { if (event.key === "Escape") onCancel(); }}
        aria-label={`Change ${item.name}`}>
        <label className="toBuyName">Item
          <input value={name} required maxLength={160} autoComplete="off" autoFocus list={listId}
            onChange={(event) => {
              const typed = event.target.value;
              const match = found.find((v) => label(v) === typed);
              setName(typed);
              if (match) setVariant({ id: match.id, label: label(match) });
              else if (!variant || typed !== variant.label) setVariant(typed === item.name && item.variant ? { id: item.variant, label: item.product } : null);
            }} />
        </label>
        <datalist id={listId}>{found.map((v) => <option key={v.id} value={label(v)}>{v.category}</option>)}</datalist>
        <label>How many<input type="number" min="0.001" step="any" inputMode="decimal" required value={count} onChange={(event) => setCount(event.target.value)} /></label>
        <label>Unit<input value={unit} maxLength={30} autoComplete="off" placeholder="pcs, cartons" onChange={(event) => setUnit(event.target.value)} /></label>
        <label>Price each ({businessCurrency()})<input type="number" min="0" step="0.01" inputMode="decimal" value={price} placeholder="If you know it"
          onChange={(event) => setPrice(event.target.value)} /></label>
        <div className="toBuyLineTotal" aria-live="polite"><span>Total</span><strong>{total == null ? "—" : money(total)}</strong></div>
        <div className="toBuyEditButtons">
          <button disabled={busy || !name.trim()}>Save</button>
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
        </div>
        <label className="toBuyNote">Note<input value={note} maxLength={200} autoComplete="off" placeholder="e.g. from the Luthuli supplier" onChange={(event) => setNote(event.target.value)} /></label>
        <p className="muted toBuyHint">{variant ? `Linked to your product ${variant.label}.` : "Not linked to one of your products."}</p>
      </form>
    </li>
  );
}

// A line on the list: how many and the price each can be changed right here (the totals follow as you type); Edit changes everything.
function ItemRow({ item, draft, canChange, canRemove, onDraft, onSave, onTick, onEdit, onRemove }) {
  const count = draft?.count ?? plain(item.count);
  const price = draft?.unit_price ?? (item.unit_price == null ? "" : plain(item.unit_price));
  const total = lineTotal(count, price);
  const save = () => {
    if (!draft) return;
    if (!num(count)) { onDraft(item.id, null); return; }  // an empty or zero count is not kept
    onSave(item, { count, unit_price: price === "" ? null : price });
  };
  const keys = (event) => { if (event.key === "Enter") event.currentTarget.blur(); };
  const editable = canChange;
  return (
    <li className={item.bought ? "bought" : undefined}>
      <label className="toBuyTick">
        <input type="checkbox" checked={item.bought} disabled={!canChange} onChange={() => onTick(item)}
          aria-label={`${item.bought ? "Not bought yet" : "Bought"}: ${item.name}`} />
        <span className="toBuyWhat"><strong>{item.name}</strong>
          {(item.product || item.note) && <small>{[item.product && item.product !== item.name && `Your product: ${item.product}`, item.note].filter(Boolean).join(" · ")}</small>}</span>
      </label>
      <span className="toBuyQty" data-label="How many">
        {editable ? <input type="number" min="0.001" step="any" inputMode="decimal" value={count} aria-label={`How many ${item.name}`}
          onChange={(event) => onDraft(item.id, { count: event.target.value, unit_price: price })} onBlur={save} onKeyDown={keys} /> : <span>{plain(item.count)}</span>}
        <small>{item.unit}</small>
      </span>
      <span className="toBuyEach" data-label="Price each">
        {editable ? <input type="number" min="0" step="0.01" inputMode="decimal" value={price} placeholder="—" aria-label={`Price each for ${item.name}`}
          onChange={(event) => onDraft(item.id, { count, unit_price: event.target.value })} onBlur={save} onKeyDown={keys} />
          : <span>{item.unit_price == null ? "—" : money(item.unit_price)}</span>}
      </span>
      <span className="toBuyTotalCell" data-label="Total">{total == null ? <span className="muted toBuyNoPrice">No price</span> : <span>{money(total)}</span>}</span>
      <span className="toBuyActions">
        {canChange && <button type="button" className="secondary toBuyRemove" onClick={() => onEdit(item)} aria-label={`Edit ${item.name}`}>Edit</button>}
        {canRemove && <button type="button" className="secondary toBuyRemove" onClick={() => onRemove(item)} aria-label={`Remove ${item.name}`}>Remove</button>}
      </span>
    </li>
  );
}

// What you have with you against what the list needs. Kept on this device only; it is not the business's money.
function MoneyCheck({ need, unpriced }) {
  const [have, setHave] = useState(readHave);
  const gap = num(have) == null ? null : num(have) - need;
  return (
    <div className="toBuyStat toBuyHave">
      <label htmlFor="to-buy-have">Money you have</label>
      <input id="to-buy-have" type="number" min="0" step="1" inputMode="decimal" placeholder="Type how much" value={have}
        onChange={(event) => { setHave(event.target.value); keepHave(event.target.value); }} />
      <span className={gap == null ? "muted" : gap >= 0 ? "good" : "short"} role="status">
        {gap == null ? "To see if it is enough" : gap >= 0 ? `Enough: ${money(gap)} left over` : `Short by ${money(-gap)}`}
        {gap != null && unpriced > 0 ? `, not counting ${unpriced} without a price` : ""}</span>
    </div>
  );
}

// A scratch list of what you are about to buy, with what it comes to. Only notes: it never changes stock, money or the books.
export function ToBuyPage() {
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [data, setData] = useState();
  const [drafts, setDrafts] = useState({});  // lines being changed and not saved yet, so the totals follow the typing
  const [error, setError] = useState("");
  const [problem, setProblem] = useState("");
  const [editing, setEditing] = useState(null);  // the line open for changing everything on it
  const load = async () => {
    try {
      setData(await api("/api/v1/to-buy/"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load);
  const act = async (path, options, done) => {
    setProblem("");
    try {
      setData(await api(path, options));
      done?.();
      return true;
    } catch (err) {
      setProblem(err.message);
      return false;
    }
  };
  const draft = (id, value) => setDrafts((all) => { const next = { ...all }; if (value) next[id] = value; else delete next[id]; return next; });
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const left = data.items.filter((item) => !item.bought);
  const bought = data.items.filter((item) => item.bought);
  const totalOf = (item) => (drafts[item.id] ? lineTotal(drafts[item.id].count, drafts[item.id].unit_price) : item.total == null ? null : Number(item.total));
  const need = left.reduce((sum, item) => sum + (totalOf(item) ?? 0), 0);
  const unpriced = left.filter((item) => totalOf(item) == null).length;
  const canSearch = (user?.organization?.enabled_modules || []).includes("inventory") && can("catalog.view_product");
  const row = (item) => (editing === item.id
    ? <EditItem key={item.id} item={item} canSearch={canSearch} onCancel={() => setEditing(null)}
      onSave={(it, change) => act(`/api/v1/to-buy/${it.id}/`, { method: "PATCH", body: JSON.stringify(change) }, () => { draft(it.id, null); setEditing(null); })} />
    : <ItemRow key={item.id} item={item} draft={drafts[item.id]} canChange={can("core.change_tobuyitem")} canRemove={can("core.delete_tobuyitem")}
      onDraft={draft} onSave={(it, change) => act(`/api/v1/to-buy/${it.id}/`, { method: "PATCH", body: JSON.stringify(change) }, () => draft(it.id, null))}
      onTick={(it) => act(`/api/v1/to-buy/${it.id}/`, { method: "PATCH", body: JSON.stringify({ bought: !it.bought }) })}
      onEdit={(it) => { draft(it.id, null); setEditing(it.id); }}
      onRemove={(it) => act(`/api/v1/to-buy/${it.id}/`, { method: "DELETE" }, () => { draft(it.id, null); if (editing === it.id) setEditing(null); })} />);
  const columns = <div className="toBuyColumns" aria-hidden="true"><span>Item</span><span>How many</span><span>Price each</span><span>Total</span><span /></div>;
  return (
    <div className="toBuyPage">
      <header className="toBuyHead">
        <div>
          <h1>To buy</h1>
          <p className="muted">A scratch list of what you are about to buy, and what it comes to. It never changes your stock or money; each item
            leaves the list by itself once you receive it into stock.</p>
        </div>
        {left.length > 0 && <button type="button" className="secondary" onClick={() => window.print()}>Print the list</button>}
      </header>

      <dl className="toBuyStats">
        <div className="toBuyStat need"><dt>Money to carry</dt><dd><strong>{money(need)}</strong>
          <span>For {left.length} {left.length === 1 ? "item" : "items"} still to buy{unpriced ? `; ${unpriced} without a price not counted` : ""}</span></dd></div>
        <div className="toBuyStat"><dt>Spent so far</dt><dd><strong>{money(data.bought_total)}</strong>
          <span>{bought.length ? `${bought.length} ticked as bought` : "Nothing ticked yet"}</span></dd></div>
        <MoneyCheck need={need} unpriced={unpriced} />
      </dl>

      {can("core.add_tobuyitem") && <AddItem canSearch={canSearch} onAdded={async (item) => {
        setData(await api("/api/v1/to-buy/", { method: "POST", body: JSON.stringify(item) }));
      }} />}
      <FormError title="Could not change the list." message={problem} />

      <section className="toBuyCard" aria-labelledby="to-buy-left">
        <header className="toBuyCardHead"><h2 id="to-buy-left">Still to buy</h2></header>
        {left.length ? <>
          {columns}
          <ul className="toBuyList">{left.map(row)}</ul>
          <div className="toBuyFoot"><span>Total to carry</span><strong>{money(need)}</strong></div>
        </> : <Empty>Nothing to buy. Add what you need above.</Empty>}
      </section>
      {bought.length > 0 && <section className="toBuyCard toBuyDone" aria-labelledby="to-buy-done">
        <header className="toBuyCardHead">
          <h2 id="to-buy-done">Ticked as bought ({bought.length})</h2>
          {can("core.delete_tobuyitem") && <button type="button" className="secondary toBuyRemove" onClick={() => act("/api/v1/to-buy/", { method: "DELETE" })}>Clear these</button>}
        </header>
        {columns}
        <ul className="toBuyList">{bought.map(row)}</ul>
        <div className="toBuyFoot"><span>Spent</span><strong>{money(data.bought_total)}</strong></div>
      </section>}
    </div>
  );
}
