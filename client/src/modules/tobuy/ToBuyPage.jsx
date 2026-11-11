import { useEffect, useRef, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const label = (v) => (!v.variant_name || v.variant_name === "Standard" ? v.product_name : `${v.product_name} ${v.variant_name}`);

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

function AddItem({ canSearch, onAdded }) {
  const [name, setName] = useState("");
  const [variant, setVariant] = useState(null);
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const first = useRef(null);
  const found = useProductSuggestions(variant ? "" : name, canSearch);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onAdded({ name, variant: variant?.id ?? null, quantity, price: price === "" ? null : price, note });
      setName(""); setVariant(null); setQuantity(""); setPrice(""); setNote("");
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
        <label>How many<input value={quantity} maxLength={40} autoComplete="off" placeholder="e.g. 10, 1 carton" onChange={(event) => setQuantity(event.target.value)} /></label>
        <label>Rough price ({businessCurrency()})<input type="number" min="0" step="0.01" value={price} placeholder="Optional" onChange={(event) => setPrice(event.target.value)} /></label>
        <label className="toBuyNote">Note<input value={note} maxLength={200} autoComplete="off" placeholder="e.g. from the Luthuli supplier" onChange={(event) => setNote(event.target.value)} /></label>
        <button disabled={busy || !name.trim()}>Add</button>
      </div>
      <p className="muted toBuyHint">{variant ? `Linked to your product ${variant.label}: it leaves the list when you receive it into stock.`
        : "Pick one of your products from the suggestions to link it, or type anything new: it leaves the list when you receive a product of that name."}</p>
      <FormError title="Could not add it." message={error} />
    </form>
  );
}

function ItemRow({ item, canChange, canRemove, onChange, onRemove }) {
  return (
    <li className={item.bought ? "bought" : undefined}>
      <label className="toBuyTick">
        <input type="checkbox" checked={item.bought} disabled={!canChange} onChange={() => onChange(item, { bought: !item.bought })}
          aria-label={`${item.bought ? "Not bought yet" : "Bought"}: ${item.name}`} />
        <span className="toBuyWhat"><strong>{item.name}</strong>
          {(item.product || item.note) && <small>{[item.product && item.product !== item.name && `Your product: ${item.product}`, item.note].filter(Boolean).join(" · ")}</small>}</span>
      </label>
      <span className="toBuyQty">{item.quantity || "—"}</span>
      <span className="toBuyPrice">{item.price != null ? money(item.price) : "—"}</span>
      {canRemove && <button type="button" className="secondary toBuyRemove" onClick={() => onRemove(item)} aria-label={`Remove ${item.name}`}>Remove</button>}
    </li>
  );
}

// A scratch list of what you are about to buy. Only notes: it never changes stock, money or the books.
export function ToBuyPage() {
  const { user } = useAuth();
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [problem, setProblem] = useState("");
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
  const act = async (path, options) => {
    setProblem("");
    try {
      setData(await api(path, options));
    } catch (err) {
      setProblem(err.message);
    }
  };
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const left = data.items.filter((item) => !item.bought);
  const bought = data.items.filter((item) => item.bought);
  const canSearch = (user?.organization?.enabled_modules || []).includes("inventory") && can("catalog.view_product");
  const row = (item) => <ItemRow key={item.id} item={item} canChange={can("core.change_tobuyitem")} canRemove={can("core.delete_tobuyitem")}
    onChange={(it, change) => act(`/api/v1/to-buy/${it.id}/`, { method: "PATCH", body: JSON.stringify(change) })}
    onRemove={(it) => act(`/api/v1/to-buy/${it.id}/`, { method: "DELETE" })} />;
  return (
    <div className="toBuyPage">
      <header className="toBuyHead">
        <div>
          <h1>To buy</h1>
          <p className="muted">A scratch list of what you are about to buy. It never changes your stock or money; each item leaves the list by itself
            once you receive it into stock.</p>
        </div>
        {left.length > 0 && <button type="button" className="secondary" onClick={() => window.print()}>Print the list</button>}
      </header>
      {can("core.add_tobuyitem") && <AddItem canSearch={canSearch} onAdded={async (item) => {
        setData(await api("/api/v1/to-buy/", { method: "POST", body: JSON.stringify(item) }));
      }} />}
      <FormError title="Could not change the list." message={problem} />
      <section className="toBuyCard" aria-labelledby="to-buy-left">
        <header className="toBuyCardHead">
          <h2 id="to-buy-left">Still to buy</h2>
          <span className="toBuyTotal">{left.length ? <>{left.length} {left.length === 1 ? "item" : "items"} · about <strong>{money(data.left_price)}</strong>
            {data.unpriced > 0 && <small> ({data.unpriced} without a price)</small>}</> : null}</span>
        </header>
        {left.length ? <>
          <div className="toBuyColumns" aria-hidden="true"><span>Item</span><span>How many</span><span>Rough price</span><span /></div>
          <ul className="toBuyList">{left.map(row)}</ul>
        </> : <Empty>Nothing to buy. Add what you need above.</Empty>}
      </section>
      {bought.length > 0 && <section className="toBuyCard toBuyDone" aria-labelledby="to-buy-done">
        <header className="toBuyCardHead">
          <h2 id="to-buy-done">Ticked as bought ({bought.length})</h2>
          {can("core.delete_tobuyitem") && <button type="button" className="secondary toBuyRemove" onClick={() => act("/api/v1/to-buy/", { method: "DELETE" })}>Clear these</button>}
        </header>
        <ul className="toBuyList">{bought.map(row)}</ul>
      </section>}
    </div>
  );
}
