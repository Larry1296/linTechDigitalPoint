import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
const PAID = { CASH: "paid now in cash", MPESA: "paid now by M-Pesa", BANK: "paid now by bank" };

export function QuickReceivePage({ defaultSource = "PURCHASE" }) {
  const [source, setSource] = useState(defaultSource);
  // Opened from a product page (?variant=): the item, supplier, buying price, payment and compartment repeat its last
  // delivery, so only the quantity is asked. "Change" shows the fields to correct any of them.
  const [params] = useSearchParams();
  const variantId = params.get("variant");
  const [prefilled, setPrefilled] = useState(null), [editing, setEditing] = useState(false), [shelf, setShelf] = useState(null);
  const quantityBox = useRef(null);
  const [query, setQuery] = useState(''), [item, setItem] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [receipt, setReceipt] = useState(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [details, setDetails] = useState({ ...NEW_RECEIPT_COSTS, supplier_name: "", external_reference: "" });
  const [quantity, setQuantity] = useState(""), [cost, setCost] = useState("");
  const opening = source === "OPENING";
  useEffect(() => {
    if (!variantId) return undefined;
    let live = true;
    api(`/api/v1/inventory/variants/${variantId}/receive-defaults/`).then((data) => {
      if (!live) return;
      const packOf = Math.max(1, Number(data.item.pack_size || 1));
      setItem(data.item); setQuery(data.item.product_name); setShelf(data.shelf);
      setCost(data.unit_cost == null ? "" : String(Math.round(Number(data.unit_cost) / packOf * 100) / 100));
      setDetails((old) => ({ ...old, supplier_name: data.supplier_name || "", document_status: data.document_status || "NO_DOCUMENT",
        payment_method: data.payment_method || "" }));
      const known = data.unit_cost != null;
      setPrefilled(known ? data : null); setEditing(!known);
      setTimeout(() => quantityBox.current?.focus(), 0);
    }).catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [variantId]);
  // This screen always ADDS to what is recorded; it never replaces the count. Say so when the item already has stock.
  const already = item ? Number(item.available || 0) : 0;
  // An item sold in packs (paper 2 sheets for 5) is counted here in pieces and kept as packs.
  const size = Math.max(1, Number(item?.pack_size || 1));
  const piece = size > 1 ? `${(item.piece_name || "piece").replace(/s$/i, "")}s` : "";
  const packs = size > 1 ? Math.round(Number(quantity || 0) / size * 1000) / 1000 : Number(quantity || 0);
  const packCost = size > 1 && cost !== "" ? String(Math.round(Number(cost) * size * 100) / 100) : cost;
  const goodsTotal = packs * Number(packCost || 0);
  // A repeated payment pays for this delivery in full unless the amount is changed by hand.
  const sendDetails = prefilled && !editing && details.payment_method ? { ...details, payment_amount: String(goodsTotal) } : details;
  const submit = async event => {
    event.preventDefault(); if (!item || busy) return;
    const problem = !(Number(quantity) > 0) ? "Enter how many you have." : opening ? (cost !== "" && Number(cost) < 0 ? "The buying price cannot be negative." : "")
      : receiptCostsProblem(sendDetails) || (!(Number(cost) > 0) ? "Enter the buying price for one unit." : "");
    if (problem) { setError(problem); return; }
    if (opening && already > 0 && !(await confirmAction({
      title: `Add ${packs} more?`,
      text: `The system already has ${already} of ${item.product_name}. This will make it ${already + packs}. `
        + "If you only want to correct the count, cancel and use Adjust stock instead.",
      confirmButtonText: `Yes, add ${packs} more`,
    }))) return;
    setBusy(true); setError(''); setReceipt(null);
    // Opening stock with no known buying price is kept without a value ("cost pending") until the price is added.
    const unknownCost = opening && !(Number(cost) > 0);
    const placements = shelf && !opening ? [{ shelf_id: shelf.id, quantity: String(packs) }] : [];
    const line = { variant_id: item.id, received_quantity: String(packs), placements, ...(unknownCost ? { uncosted: true } : { unit_cost: packCost }) };
    try {
      const body = opening ? { document_status: "OPENING_BALANCE", idempotency_key: key, notes: "Stock already in the shop", lines: [line] }
        : { ...receiptCostsPayload(sendDetails), idempotency_key: key, lines: [line] };
      const result = await api('/api/v1/inventory/receipts/', { method: 'POST', body: JSON.stringify(body) });
      setReceipt({ ...result, item: `${item.product_name} ${item.variant_name}`.trim(), quantity: packs, unknownCost });
      setKey(crypto.randomUUID()); setQuantity('');
      // From a product page the same item stays ready for its next delivery; otherwise the form starts again.
      if (!prefilled) { setItem(null); setQuery(''); setCost(''); setShelf(null); }
      else setPrefilled({ ...prefilled, supplier_name: details.supplier_name });
      setDetails({ ...(prefilled ? details : NEW_RECEIPT_COSTS), supplier_name: details.supplier_name, external_reference: "", payment_amount: "" });
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const quick = Boolean(prefilled) && !editing && !opening;
  const money = (value) => Number(value || 0).toLocaleString();
  return <>
    <h1>{opening ? "Add stock you already have" : "Receive stock"}</h1>
    {quick ? <div className="formCard receivePrefilled">
      <p><strong>{item.product_name} {item.variant_name}</strong> · {item.sku} · <strong>{already} already in stock</strong></p>
      <p className="muted">As last time: {prefilled.supplier_name ? <>from <b>{prefilled.supplier_name}</b> </> : ""}at <b>{money(cost)}</b> {size > 1 ? `a ${piece.replace(/s$/, "")}` : "each"},
        {" "}{details.document_status === "NO_DOCUMENT" ? "no supplier document" : "with a supplier invoice"}, {PAID[details.payment_method] || "owed to the supplier"},
        {" "}{shelf ? <>placed in <b>{shelf.display_name || shelf.code}</b></> : "not on a shelf yet"}.</p>
      <button type="button" className="secondary" onClick={() => {
        setEditing(true);
        if (details.payment_method && !details.payment_amount) setDetails({ ...details, payment_amount: String(goodsTotal || "") });
      }}>Change</button>
    </div> : <>
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
    </>}
    {item && !quick && <p>Selected: {item.product_name} {item.variant_name} · {item.sku}{item.available != null && <> · <strong>{already} already in stock</strong></>}</p>}
    {item && opening && already > 0 && <p className="notice warning" role="note">
      The system already has <strong>{already}</strong> of this item. Whatever you enter below is <strong>added</strong> to it.
      To fix a wrong count instead, use <Link to={`/admin/adjust-stock?variant=${item.id}`}>Adjust stock</Link>.
    </p>}
    <form onSubmit={submit}>
      {size > 1 && <p className="muted" role="note">This item is sold in packs of {size} {piece}. Enter {piece} here; they are kept as packs.</p>}
      <label>{opening ? (already > 0 ? `How many more ${piece} to add`.replace("  ", " ") : `How many ${piece} you have now`.replace("  ", " ")) : size > 1 ? `How many ${piece} arrived` : "Quantity received"}<input type="number" min="0.001" step="0.001" required ref={quantityBox} value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
      {size > 1 && Number(quantity) > 0 && <small className="muted" role="status">= {packs} packs of {size}{cost !== "" && Number(cost) > 0 ? `, bought at ${packCost} a pack` : ""}.</small>}
      {!quick && <label>{size > 1 ? `Buying price for one ${piece.replace(/s$/, "")}${opening ? " (if you know it)" : ""}` : opening ? "Buying price for one (if you know it)" : "Buying price for one"}
        <input type="number" min={opening ? "0" : "0.01"} step="0.01" required={!opening} value={cost} onChange={(e) => setCost(e.target.value)} placeholder={opening ? "Leave empty if unknown" : undefined} />
      </label>}
      {opening && <small className="muted">Unknown buying price? Leave it empty. The stock can still be sold; it is marked cost pending until you add the price, so profit is not guessed.</small>}
      {quick && !prefilled.supplier_name && <label>Supplier<input maxLength="180" required value={details.supplier_name} onChange={(e) => setDetails({ ...details, supplier_name: e.target.value })} /></label>}
      {quick && details.document_status !== "NO_DOCUMENT" && <ReceiptDocumentFields details={details} onChange={setDetails} />}
      {quick && Number(quantity) > 0 && <small className="muted" role="status">Total {money(goodsTotal)}{details.payment_method ? `, ${PAID[details.payment_method]}` : ", owed to the supplier"}.</small>}
      {!opening && !quick && <>
        <label>Supplier<input maxLength="180" required value={details.supplier_name} onChange={(e) => setDetails({ ...details, supplier_name: e.target.value })} /></label>
        <ReceiptDocumentFields details={details} onChange={setDetails} />
        <ReceiptCostFields details={details} onChange={setDetails} goodsTotal={goodsTotal} />
      </>}
      <button disabled={!item || busy}>{busy ? 'Recording…' : opening ? 'Add to my stock' : 'Receive stock'}</button>
      <FormError title="Could not record the stock." message={error} />
      {receipt && <FormSuccess>{receipt.quantity} × {receipt.item} added{receipt.unknownCost ? " (cost pending)" : ""}. <Link to={`/admin/receipts/${receipt.id}`}>View record {receipt.receipt_number}</Link></FormSuccess>}
    </form>
  </>;
}
