import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { confirmAction } from "../../core/ui/alerts";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";

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
  useEffect(() => {
    if (canAdjust(user))
      api("/api/v1/inventory/adjustments/")
        .then(setRows)
        .catch((e) => setError(e.message));
  }, [user]);
  if (!canAdjust(user)) return null;
  return (
    <section className="panel">
      <h2>Stock adjustment report</h2>
      {error && <p role="alert">{error}</p>}
      {!rows.length && <p>No adjustments posted.</p>}
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
            {new Date(a.created_at).toLocaleString()}
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
  const [variants, setVariants] = useState([]);
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
    if (!canAdjust(user)) return;
    let active = true;
    api("/api/v1/inventory/variants/search/?q=" + encodeURIComponent(query))
      .then((rows) => {
        if (active) setVariants(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [query, user]);
  useEffect(() => {
    if (canAdjust(user))
      api("/api/v1/locations/zones/")
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
    setCounted("");
    setResult(null);
    requestKey.current = null;
  }, [shelf]);
  if (!canAdjust(user))
    return <p role="alert">Stock adjustment permission is required.</p>;
  const balances = context?.balances.filter((b) => b.shelf_id === shelf) || [];
  const current = balances.reduce((sum, b) => sum + Number(b.quantity), 0);
  const reserved = balances.reduce((sum, b) => sum + Number(b.reserved), 0);
  const difference =
    counted === "" ? null : Number((Number(counted) - current).toFixed(3));
  const valid =
    context &&
    shelf &&
    counted !== "" &&
    Number.isFinite(Number(counted)) &&
    Number(counted) >= reserved &&
    difference !== 0 &&
    reason &&
    (difference < 0 || lot || cost !== "");
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
      {error && <p role="alert">{error}</p>}
      {result && (
        <p role="status">
          Adjustment #{result.id} posted. Quantity: {result.quantity_after}.
        </p>
      )}
      <form className="panel" onSubmit={post}>
        <fieldset disabled={busy}>
          <label>
            Search variant or SKU
            <input value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label>
            Exact variant
            <select
              required
              value={variant}
              onChange={(e) => setVariant(e.target.value)}
            >
              <option value="">Choose variant</option>
              {variant &&
                context &&
                !variants.some((v) => String(v.id) === String(variant)) && (
                  <option value={variant}>
                    {context.display_name} · {context.sku}
                  </option>
                )}
              {variants.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.product_name} — {v.variant_name} · {v.sku}
                </option>
              ))}
            </select>
          </label>
          {zones.length > 0 && (
            <PhysicalLocationPicker
              zones={zones}
              value={shelf}
              onChange={setShelf}
              required
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
                Stock lot
                <select value={lot} onChange={(e) => setLot(e.target.value)}>
                  <option value="">New adjustment lot (found stock)</option>
                  {context.lots.map((l) => (
                    <option key={l.id} value={l.id}>
                      Lot {l.id} · {l.reference}
                    </option>
                  ))}
                </select>
              </label>
              {!lot && (
                <label>
                  Found stock unit cost (KSh)
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
          <button disabled={!valid || busy}>Review and post adjustment</button>
        </fieldset>
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
                {m.movement_type} · {m.shelf} · Lot {m.lot_id} · Quantity{" "}
                {m.quantity}
              </p>
              {m.adjustment_id && (
                <p>
                  {m.quantity_before} → {m.quantity_after} · {m.reason}
                </p>
              )}
              <p>
                {m.notes} · {m.reference} · {m.administrator} ·{" "}
                {new Date(m.created_at).toLocaleString()}
              </p>
            </article>
          ))}
        </section>
      )}
      <AdjustmentReport key={result?.id || "initial"} />
    </>
  );
}
