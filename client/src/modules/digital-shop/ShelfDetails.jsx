import { businessCurrency, businessTimeZone } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorState, Loading } from "../../components/States";
import { loadShelfContents, updateShelf } from "./api";
import { apiUrl } from "../../core/api/client";

const MOVEMENTS = {
  PURCHASE_RECEIPT: "Received", OPENING_STOCK: "Opening stock", SALE: "Sold", TRANSFER: "Transferred",
  STOCK_ADJUSTMENT: "Count adjusted", MANUAL_ADJUSTMENT: "Count adjusted", ORDER_RESERVATION: "Reserved",
  RESERVATION_RELEASE: "Reservation released", CYBER_CONSUMPTION: "Used for a service",
};
const number = (value) => Number(value).toLocaleString("en-KE", { maximumFractionDigits: 3 });
const money = (value) => `${businessCurrency()} ${Number(value).toLocaleString("en-KE", { maximumFractionDigits: 2 })}`;
const date = (value) => new Date(value).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric", timeZone: businessTimeZone() });

function ItemPhoto({ item }) {
  if (item.image) return <img className="shelfItemPhoto" src={apiUrl(item.image)} alt="" loading="lazy" />;
  return <span className="shelfItemPhoto shelfItemInitials" aria-hidden="true">{item.product.slice(0, 2).toUpperCase()}</span>;
}

export function ShelfDetails({ shelfId, onClose, onUpdated }) {
  const [data, setData] = useState();
  const [loadError, setLoadError] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [query, setQuery] = useState("");
  const load = useCallback(() => {
    setLoadError("");
    return loadShelfContents(shelfId).then(setData).catch((e) => setLoadError(e.message));
  }, [shelfId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const closeOnEscape = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  const save = async (e) => {
    e.preventDefault();
    setSaving(true); setSaveError("");
    try {
      await updateShelf(shelfId, Object.fromEntries(new FormData(e.currentTarget)));
      setEditing(false);
      onUpdated();
      await load();
    } catch (error) {
      setSaveError(error.message);
    } finally {
      setSaving(false);
    }
  };
  const place = data?.location;
  const title = place?.level ? `Level ${place.level} · Shelf ${place.position}` : data?.shelf.display_name;
  const search = query.trim().toLowerCase();
  const items = (data?.items || []).filter((item) => !search ||
    [item.product, item.variant, item.sku, item.category].some((text) => text?.toLowerCase().includes(search)));
  return (
    <div className="shelfOverlay" role="presentation" onMouseDown={onClose}>
      <div className="shelfPanel" role="dialog" aria-modal="true" aria-label={title ? `Shelf ${title}` : "Shelf details"}
        onMouseDown={(event) => event.stopPropagation()}>
        <header className="shelfPanelHeader">
          <div>
            <span className="eyebrow">{place ? [place.area, place.rack].filter(Boolean).join(" · ") : "Shelf"}</span>
            <h2>{title || "Loading…"}</h2>
            {data && <small className="muted">{data.shelf.code}{data.shelf.physical_label ? ` · Label ${data.shelf.physical_label}` : ""}</small>}
          </div>
          <button type="button" className="shelfClose" onClick={onClose} aria-label="Close shelf details">×</button>
        </header>
        {loadError && !data ? <ErrorState message={loadError} retry={load} /> : !data ? <Loading /> : <>
          <section className="shelfStats" aria-label="Shelf totals">
            <div><span>Items</span><strong>{data.totals.items}</strong></div>
            <div><span>Units</span><strong>{number(data.totals.units)}</strong>
              {Number(data.totals.units) !== Number(data.totals.available) && <small>{number(data.totals.available)} available</small>}</div>
            <div><span>Selling value</span><strong>{money(data.totals.retail_value)}</strong></div>
            {data.show_cost && <div><span>Buying cost</span><strong>{money(data.totals.cost_value)}</strong></div>}
          </section>
          {place?.categories?.length > 0 && <p className="shelfCategories">Rack holds: {place.categories.join(", ")}</p>}

          <section className="shelfContents" aria-labelledby="shelf-items-heading">
            <div className="shelfContentsHeading">
              <h3 id="shelf-items-heading">Items on this shelf</h3>
              {data.items.length > 5 && <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Find an item on this shelf" aria-label="Find an item on this shelf" />}
            </div>
            {!data.items.length ? <div className="shelfEmpty">
              <strong>This shelf is empty.</strong>
              <p className="muted">Stock placed here when you receive it will be listed with its quantity and value.</p>
              <Link className="button" to="/admin/receive">Receive stock</Link>
            </div> : !items.length ? <p className="muted">No item on this shelf matches “{query}”.</p> : <ul className="shelfItems">
              {items.map((item) => <li key={item.variant_id} className="shelfItem">
                <ItemPhoto item={item} />
                <div className="shelfItemMain">
                  <strong>{item.product}</strong>
                  <span>{item.variant}</span>
                  <small className="muted">SKU {item.sku} · {item.category}</small>
                  <dl className="shelfItemFacts">
                    <div><dt>Price</dt><dd>{money(item.selling_price)} each</dd></div>
                    <div><dt>Selling value</dt><dd>{money(item.retail_value)}</dd></div>
                    {data.show_cost && <div><dt>Buying cost</dt><dd>{money(item.cost_value)}</dd></div>}
                    {item.last_received && <div><dt>Last received</dt><dd>{date(item.last_received)}{item.batches > 1 ? ` · ${item.batches} deliveries` : ""}</dd></div>}
                  </dl>
                  <div className="shelfItemActions">
                    <Link to={`/admin/product-lookup?product=${item.product_id}&variant=${item.variant_id}`}>View product</Link>
                    <Link to={`/admin/adjust-stock?variant=${item.variant_id}`}>Adjust count</Link>
                  </div>
                </div>
                <div className="shelfItemQty">
                  <strong>{number(item.quantity)}</strong>
                  <span>units</span>
                  {Number(item.reserved) > 0 && <small>{number(item.reserved)} reserved</small>}
                </div>
              </li>)}
            </ul>}
          </section>

          {data.recent_movements.length > 0 && <section className="shelfActivity" aria-labelledby="shelf-activity-heading">
            <h3 id="shelf-activity-heading">Recent activity</h3>
            <ul>
              {data.recent_movements.map((move, index) => <li key={index}>
                <span className={`shelfMove ${move.direction}`}>{move.direction === "in" ? "+" : "−"}{number(move.quantity)}</span>
                <span><strong>{MOVEMENTS[move.type] || move.type.replaceAll("_", " ").toLowerCase()}</strong> · {move.product}
                  <small className="muted"> {move.reference} · {date(move.created_at)}</small></span>
              </li>)}
            </ul>
          </section>}

          <details className="shelfIdentity" open={editing || undefined}>
            <summary>Shelf details</summary>
            <dl>
              <div><dt>System code</dt><dd>{data.shelf.code}</dd></div>
              <div><dt>Physical label</dt><dd>{data.shelf.physical_label || "Not labelled yet"}</dd></div>
              <div><dt>Display name</dt><dd>{data.shelf.display_name}</dd></div>
            </dl>
            {editing ? <form className="shelfEditForm" onSubmit={save}>
              <FormField label="Physical label" name="physical_label" defaultValue={data.shelf.physical_label} placeholder="e.g. AL1C1" />
              <FormField label="Display name" name="display_name" defaultValue={data.shelf.display_name} />
              <div className="shelfEditActions">
                <button disabled={saving}>{saving ? "Saving…" : "Save shelf"}</button>
                <button type="button" className="secondary" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
              </div>
              <FormError title="Could not save the shelf." message={saveError} />
            </form> : <button type="button" className="secondary" onClick={() => setEditing(true)}>Edit shelf label</button>}
          </details>
        </>}
        <footer className="shelfActions">
          <Link className="button" to="/admin/receive">Receive stock</Link>
          <button type="button" className="secondary" onClick={() => window.print()} disabled={!data}>Print label</button>
        </footer>
      </div>
    </div>
  );
}
