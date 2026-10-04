import { businessCurrency, businessTimeZone } from "../../core/organization/presentation";
import { label } from "../../core/ui/labels";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { loadZonesIfUsed } from "../digital-shop/api";
import { confirmAction } from "../../core/ui/alerts";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { ProductSearch } from "../storefront/components/ProductSearch";

const reasons = [
  "Opening stock correction",
  "Physical count variance",
  "Damaged item",
  "Lost item",
  "Data-entry correction",
  "Found stock",
];
export const canAdjust = (user) =>
  Boolean(
    user?.is_superuser || user?.permissions?.includes("inventory.adjust_stock"),
  );

export function AdjustmentReport() {
  const { user } = useAuth();
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const load = () => {
    if (canAdjust(user))
      api("/api/v1/inventory/adjustments/")
        .then(setRows)
        .catch((e) => setError(e.message));
  };
  useEffect(load, [user]);
  useLiveRefresh(load);
  if (!canAdjust(user)) return null;
  return (
    <section className="panel">
      <h2>Stock adjustment report</h2>
      {error && <p role="alert">{error}</p>}
      {!rows.length && <p>No stock changes yet.</p>}
      {rows.map((a) => (
        <article key={a.id}>
          <b>
            {a.display_name} · {a.sku}
          </b>
          <p>
            {a.shelf}: {a.quantity_before} → {a.quantity_after} (
            {Number(a.amount) > 0 ? "+" : ""}
            {Number(a.amount)}) · {a.reason}
          </p>
          <p>
            {a.notes} · {a.reference} · {a.administrator} ·{" "}
            {new Date(a.created_at).toLocaleString(undefined, {timeZone: businessTimeZone()})}
          </p>
        </article>
      ))}
    </section>
  );
}

export function StockAdjustmentPage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const [variant, setVariant] = useState(params.get("variant") || "");
  const [query, setQuery] = useState("");
  const [zones, setZones] = useState([]);
  const [shelf, setShelf] = useState("");
  const [context, setContext] = useState(null);
  const [counted, setCounted] = useState("");
  const [lot, setLot] = useState("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [reference, setReference] = useState("");
  const [cost, setCost] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const requestKey = useRef(null);
  const posting = useRef(false);
  useEffect(() => {
    if (canAdjust(user))
      loadZonesIfUsed(user)
        .then(setZones)
        .catch((e) => setError(e.message));
  }, [user]);
  useEffect(() => {
    setContext(null);
    setCounted("");
    setResult(null);
    setLot("");
    setError("");
    requestKey.current = null;
    if (!variant || !canAdjust(user)) return;
    let active = true;
    api(`/api/v1/inventory/adjustments/variants/${variant}/`)
      .then((data) => {
        if (active) {
          setContext(data);
          if (data.lots.length === 1) setLot(String(data.lots[0].id));
          // Start on the place that holds this item, so the form opens with what is stored.
          const places = data.locations || [];
          setShelf((current) =>
            places.some((p) => p.shelf_id === current) ? current : places[0]?.shelf_id ?? current,
          );
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [variant, user]);
  useEffect(() => {
    // Prefill the count with the stored quantity; the user changes only what differs.
    const stored = (context?.balances || [])
      .filter((b) => b.shelf_id === shelf)
      .reduce((sum, b) => sum + Number(b.quantity), 0);
    setCounted(context && shelf ? String(stored) : "");
    requestKey.current = null;
  }, [shelf, context]);
  useEffect(() => setResult(null), [shelf]);
  if (!canAdjust(user))
    return <p role="alert">Stock adjustment permission is required.</p>;
  const locations = context?.locations || [];
  const totalStored = locations.reduce((sum, l) => sum + Number(l.quantity), 0);
  const virtualShelf = locations.some((l) => l.shelf_id === shelf && l.virtual);
  const balances = context?.balances.filter((b) => b.shelf_id === shelf) || [];
  const current = balances.reduce((sum, b) => sum + Number(b.quantity), 0);
  const reserved = balances.reduce((sum, b) => sum + Number(b.reserved), 0);
  const difference =
    counted === "" ? null : Number((Number(counted) - current).toFixed(3));
  // The first thing still stopping the adjustment, shown beside the disabled button.
  const blocker =
    !variant ? "Search and choose the item to adjust."
    : !context ? "Loading this item's stock…"
    : !zones.length && !locations.length ? "No shop areas are set up. Add a shop area, rack and compartment first."
    : !shelf ? "Choose the compartment: shop area, rack, level and compartment."
    : counted === "" ? "Enter the physical counted quantity."
    : !Number.isFinite(Number(counted)) ? "The counted quantity must be a number."
    : Number(counted) < 0 ? "The counted quantity cannot be negative."
    : Number(counted) < reserved ? `The count cannot be below the ${reserved} reserved units.`
    : difference === 0 ? `The count matches the system quantity (${current}), so there is nothing to adjust.`
    : difference > 0 && !lot && cost === "" ? "Enter what one found item cost, or choose which delivery it belongs to."
    : !reason ? "Choose a reason."
    : "";
  const valid = !blocker;
  async function post(event) {
    event.preventDefault();
    if (!valid || posting.current) return;
    posting.current = true;
    setBusy(true);
    setError("");
    try {
      if (
        !(await confirmAction({
          title: "Post stock adjustment?",
          text: `${context.display_name} · ${context.sku} · ${zones.flatMap((z) => (z.stacks || []).flatMap((r) => (r.levels || []).flatMap((l) => l.shelves || []))).find((s) => s.id === shelf)?.physical_label || "Selected compartment"}: ${current} → ${counted} (${difference > 0 ? "+" : ""}${difference}). Reason: ${reason}. This creates a permanent audit record.`,
          confirmButtonText: "Post adjustment",
        }))
      )
        return;
      const payload = {
        variant_id: Number(variant),
        shelf_id: shelf,
        expected_quantity: current,
        counted_quantity: counted,
        reason,
        notes,
        reference,
        confirmed: true,
        ...(difference > 0
          ? lot
            ? { lot_id: Number(lot) }
            : { new_lot_unit_cost: cost }
          : {}),
      };
      const signature = JSON.stringify(payload);
      if (requestKey.current?.signature !== signature)
        requestKey.current = { signature, key: crypto.randomUUID() };
      const posted = await api("/api/v1/inventory/adjustments/", {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          idempotency_key: requestKey.current.key,
        }),
      });
      setResult(posted);
      setCounted("");
      setContext(
        await api(`/api/v1/inventory/adjustments/variants/${variant}/`),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      posting.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      <h1>Adjust Stock</h1>
      <p>
        Enter the physical count, including reserved units. Posted adjustments
        cannot be edited; correct mistakes with another adjustment.
      </p>
      <form className="panel" onSubmit={post}>
        <fieldset disabled={busy}>
          <div className="stockItemSearch">
            <span>Find the item</span>
            <ProductSearch
              embedded
              label="Find the item to adjust"
              value={query}
              onChange={setQuery}
              endpoint="/api/v1/inventory/variants/search/"
              minLength={1}
              limit={50}
              onSelect={(row) => {
                setVariant(String(row.id));
                setQuery("");
              }}
              onSearch={() => {}}
              exactScan
              renderResult={(row) => (
                <span className="productSearchDetails">
                  <strong>{row.product_name} — {row.variant_name}</strong>
                  <span>{row.sku}{row.category ? ` · ${row.category}` : ""}</span>
                  <span>{Number(row.available)} in stock</span>
                </span>
              )}
              placeholder="Start typing a name, item code or barcode…"
            />
            {variant && context && (
              <p className="muted">
                Adjusting: <strong>{context.display_name}</strong> · {context.sku}
              </p>
            )}
          </div>
          {locations.length > 0 && (
            <fieldset className="stockLocations">
              <legend>
                Where the stock is · {totalStored} in the system in total
              </legend>
              {locations.map((l) => (
                <label key={l.shelf_id} className="choiceRow">
                  <input
                    type="radio"
                    name="stock-location"
                    checked={shelf === l.shelf_id}
                    onChange={() => setShelf(l.shelf_id)}
                  />
                  <span>
                    <strong>{l.virtual ? l.name : `${l.label} — ${l.name}`}</strong>{" "}
                    · {Number(l.quantity)} in system
                    {Number(l.reserved) > 0 && ` (${Number(l.reserved)} reserved)`}
                  </span>
                </label>
              ))}
              {locations.length > 1 && (
                <small className="muted">
                  Each place is counted separately. Choose one, enter what is
                  really there, then do the next.
                </small>
              )}
            </fieldset>
          )}
          {zones.length > 0 && (
            <PhysicalLocationPicker
              zones={zones}
              // The unplaced location has no rack, so the picker shows nothing chosen for it.
              value={virtualShelf ? "" : shelf}
              onChange={(next) => {
                if (next !== "" || !virtualShelf) setShelf(next);
              }}
              required={!virtualShelf}
            />
          )}
          {context && shelf && (
            <>
              <p>
                Current system quantity: <strong>{current}</strong> · Reserved:{" "}
                {reserved}
              </p>
              <label>
                Physical counted quantity
                <input
                  type="number"
                  min={reserved}
                  step="0.001"
                  required
                  value={counted}
                  onChange={(e) => setCounted(e.target.value)}
                />
              </label>
              <p role="status">
                Adjustment:{" "}
                {difference === null
                  ? "—"
                  : `${difference > 0 ? "+" : ""}${difference}`}
              </p>
            </>
          )}
          {difference > 0 && (
            <>
              <label>
                Which delivery
                <select value={lot} onChange={(e) => setLot(e.target.value)}>
                  <option value="">New batch (found stock)</option>
                  {context.lots.map((l) => (
                    <option key={l.id} value={l.id}>
                      Delivery {l.reference} (#{l.id})
                    </option>
                  ))}
                </select>
              </label>
              {!lot && (
                <label>
                  Found stock unit cost ({businessCurrency()})
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={cost}
                    onChange={(e) => setCost(e.target.value)}
                  />
                </label>
              )}
            </>
          )}
          <label>
            Reason
            <select
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            >
              <option value="">Choose reason</option>
              {reasons.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
          <label>
            Notes
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          <label>
            Reference number
            <input
              maxLength={100}
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </label>
          <button disabled={!valid || busy} aria-describedby={blocker ? "adjustment-blocker" : undefined}>Review and post adjustment</button>
          {blocker && <p id="adjustment-blocker" className="muted" role="status">{blocker}</p>}
        </fieldset>
        <FormError title="Could not post the adjustment." message={error} />
        {result && <FormSuccess message={`Stock change #${result.id} saved. Quantity now: ${result.quantity_after}.`} />}
      </form>
      {context && (
        <section className="panel">
          <h2>Product stock history</h2>
          <b>
            {context.display_name} · {context.sku}
          </b>
          {context.history.map((m) => (
            <article key={m.id}>
              <p>
                {label(m.movement_type)} · {m.shelf} · Lot {m.lot_id} · Quantity{" "}
                {m.quantity}
              </p>
              {m.adjustment_id && (
                <p>
                  {m.quantity_before} → {m.quantity_after} · {m.reason}
                </p>
              )}
              <p>
                {m.notes} · {m.reference} · {m.administrator} ·{" "}
                {new Date(m.created_at).toLocaleString(undefined, {timeZone: businessTimeZone()})}
              </p>
            </article>
          ))}
        </section>
      )}
      <AdjustmentReport key={result?.id || "initial"} />
    </>
  );
}
