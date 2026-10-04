import { useState } from "react";
import { Link } from "react-router-dom";
import { ProductSearch } from "../storefront/components/ProductSearch";
import { api } from "../../core/api/client";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { confirmAction } from "../../core/ui/alerts";
import "../platform/platform.css";
import { NEW_RECEIPT_COSTS, ReceiptCostFields, ReceiptDocumentFields, receiptCostsPayload, receiptCostsProblem } from "./ReceiptCosts";

const SOURCES = [
  { id: "OPENING", label: "Stock I already have", hint: "Items already in the shop. Not a purchase: nothing is owed or paid." },
  { id: "PURCHASE", label: "Bought from a supplier", hint: "A new delivery or purchase, paid now or owed to the supplier." },
];

// Purchases are the everyday case; stock already in the shop is chosen on purpose or opened from its own menu link.
export function QuickReceivePage({ defaultSource = "PURCHASE" }) {
  const [source, setSource] = useState(defaultSource);
  const [query, setQuery] = useState(''), [item, setItem] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [receipt, setReceipt] = useState(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [details, setDetails] = useState({ ...NEW_RECEIPT_COSTS, supplier_name: "", external_reference: "" });
  const [quantity, setQuantity] = useState(""), [cost, setCost] = useState("");
  const opening = source === "OPENING";
  // This screen always ADDS to what is recorded; it never replaces the count. Say so when the item already has stock.
  const already = item ? Number(item.available || 0) : 0;
  const submit = async event => {
    event.preventDefault(); if (!item || busy) return;
    const problem = !(Number(quantity) > 0) ? "Enter how many you have." : opening ? (cost !== "" && Number(cost) < 0 ? "The buying price cannot be negative." : "")
      : receiptCostsProblem(details) || (!(Number(cost) > 0) ? "Enter the buying price for one unit." : "");
    if (problem) { setError(problem); return; }
    if (opening && already > 0 && !(await confirmAction({
      title: `Add ${quantity} more?`,
      text: `The system already has ${already} of ${item.product_name}. This will make it ${already + Number(quantity)}. `
        + "If you only want to correct the count, cancel and use Adjust stock instead.",
      confirmButtonText: `Yes, add ${quantity} more`,
    }))) return;
    setBusy(true); setError(''); setReceipt(null);
    // Opening stock with no known buying price is kept without a value ("cost pending") until the price is added.
    const unknownCost = opening && !(Number(cost) > 0);
    const line = { variant_id: item.id, received_quantity: quantity, placements: [], ...(unknownCost ? { uncosted: true } : { unit_cost: cost }) };
    try {
      const body = opening ? { document_status: "OPENING_BALANCE", idempotency_key: key, notes: "Stock already in the shop", lines: [line] }
        : { ...receiptCostsPayload(details), idempotency_key: key, lines: [line] };
      const result = await api('/api/v1/inventory/receipts/', { method: 'POST', body: JSON.stringify(body) });
      setReceipt({ ...result, item: `${item.product_name} ${item.variant_name}`.trim(), quantity, unknownCost });
      setKey(crypto.randomUUID()); setItem(null); setQuery('');
      setQuantity(''); setCost(''); setDetails({ ...NEW_RECEIPT_COSTS, supplier_name: details.supplier_name, external_reference: "" });
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <>
    <h1>{opening ? "Add stock you already have" : "Receive stock"}</h1>
    <fieldset className="choiceGroup stockSource">
      <legend>Where is this stock from?</legend>
      <div className="choiceGrid wideChoices">
        {SOURCES.map((option) => <button type="button" key={option.id} className={`choiceCard${source === option.id ? " selected" : ""}`}
          aria-pressed={source === option.id} onClick={() => { setSource(option.id); setError(""); }}>
          <strong>{option.label}</strong><span>{option.hint}</span>
        </button>)}
      </div>
    </fieldset>
    <p>{opening ? "Find the item, then count how many you have now. Repeat for each item." : "Choose an item, enter how many arrived and the buying price for one. You can assign shelves later."}</p>
    <p><Link to="/admin/products">Item not listed? Add it first</Link>{!opening && <> · <Link to="/admin/receive">Receive several items or choose shelves</Link></>}</p>
    <ProductSearch value={query} onChange={setQuery} endpoint="/api/v1/inventory/variants/search/" minLength={1} limit={50} onSelect={value => { setItem(value); setQuery(value.product_name); }} renderResult={row => <span>{row.product_name} — {row.variant_name} · {row.sku} · {Number(row.available)} in stock</span>} placeholder="Find item by name or barcode" />
    {item && <p>Selected: {item.product_name} {item.variant_name} · {item.sku}{item.available != null && <> · <strong>{already} already in stock</strong></>}</p>}
    {item && opening && already > 0 && <p className="notice warning" role="note">
      The system already has <strong>{already}</strong> of this item. Whatever you enter below is <strong>added</strong> to it.
      To fix a wrong count instead, use <Link to={`/admin/adjust-stock?variant=${item.id}`}>Adjust stock</Link>.
    </p>}
    <form onSubmit={submit}>
      <label>{opening ? (already > 0 ? "How many more to add" : "How many you have now") : "Quantity received"}<input type="number" min="0.001" step="0.001" required value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
      <label>{opening ? "Buying price for one (if you know it)" : "Buying price for one"}
        <input type="number" min={opening ? "0" : "0.01"} step="0.01" required={!opening} value={cost} onChange={(e) => setCost(e.target.value)} placeholder={opening ? "Leave empty if unknown" : undefined} />
      </label>
      {opening && <small className="muted">Unknown buying price? Leave it empty. The stock can still be sold; it is marked cost pending until you add the price, so profit is not guessed.</small>}
      {!opening && <>
        <label>Supplier<input maxLength="180" required value={details.supplier_name} onChange={(e) => setDetails({ ...details, supplier_name: e.target.value })} /></label>
        <ReceiptDocumentFields details={details} onChange={setDetails} />
        <ReceiptCostFields details={details} onChange={setDetails} goodsTotal={Number(quantity || 0) * Number(cost || 0)} />
      </>}
      <button disabled={!item || busy}>{busy ? 'Recording…' : opening ? 'Add to my stock' : 'Receive stock'}</button>
      <FormError title="Could not record the stock." message={error} />
      {receipt && <FormSuccess>{receipt.quantity} × {receipt.item} added{receipt.unknownCost ? " (cost pending)" : ""}. <Link to={`/admin/receipts/${receipt.id}`}>View record {receipt.receipt_number}</Link></FormSuccess>}
    </form>
  </>;
}
