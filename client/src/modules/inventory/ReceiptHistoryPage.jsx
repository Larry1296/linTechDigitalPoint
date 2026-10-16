import { businessCurrency, businessTimeZone } from "../../core/organization/presentation";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { confirmAction } from "../../core/ui/alerts";
import { FormError } from "../../components/forms/FormNotice";
import { ReceiptSupplier } from "./ReceiptSupplier";

const allowed = (user, permission) =>
  Boolean(user?.is_superuser || user?.permissions?.includes(permission));
const money = (value) => `${businessCurrency()} ${Number(value).toFixed(2)}`;
const identity = (line) =>
  `${line.product_name} — ${line.variant_name} · ${line.sku}`;

export function ReceiptHistoryPage() {
  const { user } = useAuth();
  const { id } = useParams();
  const [rows, setRows] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const canView = allowed(user, "inventory.view_stockreceipt");
  const canCorrect = allowed(user, "inventory.change_stockreceipt");
  useEffect(() => {
    if (!canView) return;
    let active = true;
    setReceipt(null);
    setSelected(null);
    setError("");
    setMessage("");
    api(`/api/v1/inventory/receipts/${id ? `${id}/` : ""}`)
      .then((data) => {
        if (active) {
          if (id) setReceipt(data);
          else setRows(data);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [id, canView]);
  if (!canView)
    return <p role="alert">Receipt history permission is required.</p>;
  return (
    <>
      <h1>Receipt History</h1>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {!id ? (
        <>
          <p>
            Latest 100 receipts. Open a receipt to review its lines and
            correction history, or to clear what it says is owed to the
            supplier.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
            }}
          >
            <label>
              Receipt ID
              <input
                type="number"
                min="1"
                value={selected || ""}
                onChange={(e) => setSelected(e.target.value)}
              />
            </label>
            {selected && (
              <Link className="button" to={`/admin/receipts/${selected}`}>
                Open receipt {selected}
              </Link>
            )}
          </form>
          {!rows && !error && <p role="status">Loading receipts…</p>}
          {rows?.length === 0 && <p>No receipts found.</p>}
          {rows?.map((r) => (
            <article className="panel" key={r.id}>
              <Link to={`/admin/receipts/${r.id}`}>
                Receipt {r.id} · {r.receipt_number}
              </Link>
              <p>
                {r.supplier_name} · {new Date(r.received_at).toLocaleString(undefined, {timeZone: businessTimeZone()})} ·{" "}
                {r.line_count} lines · {Number(r.total_units)} units
                {Number(r.owed) > 0 && <> · <strong>owed {money(r.owed)}</strong></>}
              </p>
            </article>
          ))}
        </>
      ) : (
        <>
          <Link to="/admin/receipts">← All receipts</Link>
          {!receipt && !error && <p role="status">Loading receipt…</p>}
          {receipt && (
            <>
              <h2>
                Receipt {receipt.id} · {receipt.receipt_number}
              </h2>
              <p>
                {receipt.supplier_name} ·{" "}
                {new Date(receipt.received_at).toLocaleString(undefined, {timeZone: businessTimeZone()})} ·{" "}
                {receipt.external_reference}
              </p>
              {receipt.notes && <p>{receipt.notes}</p>}
              <ReceiptSupplier
                receipt={receipt}
                can={{
                  pay: allowed(user, "accounting.add_purchasepayment"),
                  undo: allowed(user, "accounting.reverse_cashentry"),
                  markOwned: canCorrect,
                }}
                onSaved={(data, text) => {
                  setReceipt(data);
                  setMessage(text);
                }}
              />
              {receipt.lines.map((line) => (
                <section
                  className="panel"
                  key={line.id}
                  aria-label={identity(line)}
                >
                  <h3>{identity(line)}</h3>
                  <p>
                    {Number(line.quantity)} units × {money(line.unit_cost)} ={" "}
                    <strong>{money(line.line_cost)}</strong>
                  </p>
                  <p>
                    {line.placements
                      .map((p) => `${p.code}: ${Number(p.quantity)} units`)
                      .join(" · ")}
                  </p>
                  {canCorrect && selected !== line.id && (
                    <button
                      onClick={() => {
                        setSelected(line.id);
                        setMessage("");
                      }}
                    >
                      Correct receipt line
                    </button>
                  )}
                  {canCorrect && selected === line.id && (
                    <CorrectionForm
                      key={line.updated_at}
                      receipt={receipt}
                      line={line}
                      onCancel={() => setSelected(null)}
                      onSaved={(data) => {
                        setReceipt(data);
                        setSelected(null);
                        setMessage(
                          "Receipt line corrected. The permanent audit record is shown below.",
                        );
                      }}
                    />
                  )}
                  {line.corrections?.length > 0 && (
                    <div>
                      <h4>Correction history</h4>
                      {line.corrections.map((c) => (
                        <article key={c.id}>
                          <p>
                            Correction #{c.id} · {c.administrator} ·{" "}
                            {new Date(c.created_at).toLocaleString(undefined, {timeZone: businessTimeZone()})}
                          </p>
                          <ValueComparison before={c.before} after={c.after} />
                          <p>Reason: {c.reason}</p>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              ))}
            </>
          )}
        </>
      )}
    </>
  );
}

function ValueComparison({ before, after }) {
  return (
    <div className="receiptComparison">
      <table>
        <thead>
          <tr>
            <th>Value</th>
            <th>Old</th>
            <th>New</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th>Item</th>
            <td>{identity(before)}</td>
            <td>{identity(after)}</td>
          </tr>
          <tr>
            <th>Buying price per unit</th>
            <td>{money(before.unit_cost)}</td>
            <td>{money(after.unit_cost)}</td>
          </tr>
          <tr>
            <th>Received quantity</th>
            <td>{Number(before.quantity)}</td>
            <td>{Number(after.quantity)}</td>
          </tr>
          <tr>
            <th>Line total</th>
            <td>{money(before.line_total)}</td>
            <td>{money(after.line_total)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function CorrectionForm({ receipt, line, onCancel, onSaved }) {
  const [variant, setVariant] = useState(line);
  const [query, setQuery] = useState("");
  const [variants, setVariants] = useState([]);
  const [cost, setCost] = useState(String(line.unit_cost));
  const [editQuantity, setEditQuantity] = useState(false);
  const [quantity, setQuantity] = useState(String(line.quantity));
  const [placements, setPlacements] = useState(
    line.placements.map((p) => ({ ...p })),
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const posting = useRef(false);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      api("/api/v1/inventory/variants/search/?q=" + encodeURIComponent(query))
        .then((data) => {
          if (active) setVariants(data);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query]);
  const newQuantity = editQuantity ? quantity : String(line.quantity);
  const changedQuantity = Number(newQuantity) !== Number(line.quantity);
  const before = { ...line, line_total: line.line_cost };
  const after = {
    ...variant,
    quantity: newQuantity,
    unit_cost: cost,
    line_total: Number(newQuantity) * Number(cost),
  };
  const changed =
    variant.variant_id !== line.variant_id ||
    Number(cost) !== Number(line.unit_cost) ||
    changedQuantity;
  const valid =
    changed &&
    reason.trim() &&
    cost !== "" &&
    Number.isFinite(Number(cost)) &&
    Number(cost) >= 0 &&
    Number(newQuantity) > 0 &&
    (!changedQuantity ||
      placements.length === 1 ||
      Math.abs(
        placements.reduce((sum, p) => sum + Number(p.quantity), 0) -
          Number(newQuantity),
      ) < 0.000001);
  async function submit(event) {
    event.preventDefault();
    if (!valid || posting.current) return;
    posting.current = true;
    setBusy(true);
    setError("");
    try {
      if (
        !(await confirmAction({
          title: "Correct receipt line?",
          text: `Receipt ${receipt.id}, line ${line.id}. Product: ${identity(before)} → ${identity(after)}. Buying price: ${money(before.unit_cost)} → ${money(cost)}. Quantity: ${Number(line.quantity)} → ${Number(newQuantity)}. Line total: ${money(line.line_cost)} → ${money(after.line_total)}. Reason: ${reason.trim()}. This creates a permanent audit record.`,
          confirmButtonText: "Confirm correction",
        }))
      )
        return;
      const data = await api(
        `/api/v1/inventory/receipts/${receipt.id}/lines/${line.id}/correct/`,
        {
          method: "POST",
          body: JSON.stringify({
            variant_id: variant.variant_id,
            unit_cost: cost,
            received_quantity: newQuantity,
            reason: reason.trim(),
            confirmed: true,
            expected_updated_at: line.updated_at,
            ...(changedQuantity && placements.length > 1
              ? {
                  placements: placements.map((p) => ({
                    shelf_id: p.shelf_id,
                    quantity: p.quantity,
                  })),
                }
              : {}),
          }),
        },
      );
      onSaved(data);
    } catch (e) {
      setError(e.message);
    } finally {
      posting.current = false;
      setBusy(false);
    }
  }
  return (
    <form className="receiptCorrection" onSubmit={submit} aria-label="Correct receipt line">
      <fieldset disabled={busy}>
        <legend>Correct receipt line</legend>
        <label>
          Search product variant or SKU
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <label>
          Selected product variant
          <select
            value={variant.variant_id}
            onChange={(e) => {
              const selected = variants.find(
                (v) => String(v.id) === e.target.value,
              );
              if (selected)
                setVariant({ ...selected, variant_id: selected.id });
            }}
            // While typing, open into a list so every match shows at once.
            size={query.trim() ? Math.min(variants.length + 1, 10) : undefined}
          >
            {!variants.some((v) => v.id === variant.variant_id) && (
              <option value={variant.variant_id}>{identity(variant)}</option>
            )}
            {variants.map((v) => (
              <option key={v.id} value={v.id}>
                {identity(v)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Buying price per unit ({businessCurrency()})
          <input
            required
            type="number"
            min="0"
            step="0.01"
            value={cost}
            onChange={(e) => setCost(e.target.value)}
          />
        </label>
        <label className="receiptQuantityToggle">
          <input
            type="checkbox"
            checked={editQuantity}
            onChange={(e) => setEditQuantity(e.target.checked)}
          />
          Correct received quantity (only if necessary)
        </label>
        {editQuantity && (
          <>
            <p>
              Variant or quantity changes require an unused lot. Sold, allocated
              or otherwise used stock requires a reversal workflow.
            </p>
            <label>
              Received quantity
              <input
                required
                type="number"
                min="0.001"
                step="0.001"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            {placements.length > 1 &&
              placements.map((p, index) => (
                <label key={p.shelf_id}>
                  Quantity in {p.code}
                  <input
                    required
                    type="number"
                    min="0.001"
                    step="0.001"
                    value={p.quantity}
                    onChange={(e) =>
                      setPlacements((rows) =>
                        rows.map((row, i) =>
                          i === index
                            ? { ...row, quantity: e.target.value }
                            : row,
                        ),
                      )
                    }
                  />
                </label>
              ))}
          </>
        )}
        <label>
          Correction reason
          <textarea
            required
            maxLength={2000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <ValueComparison before={before} after={after} />
        <button disabled={!valid || busy}>Review correction</button>{" "}
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </fieldset>
      <FormError title="Could not post the correction." message={error} />
    </form>
  );
}
