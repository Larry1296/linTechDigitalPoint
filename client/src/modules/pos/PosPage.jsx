import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, CheckCircle2, ChevronDown, Minus, Plus, Receipt, ShoppingCart, Smartphone, Trash2, X } from "lucide-react";
import { businessCurrency } from "../../core/organization/presentation";
import { useAuth } from "../../core/auth/AuthContext";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { Empty } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { ProductActions } from "../products/ProductActions";
import { ProductSearch } from "../storefront/components/ProductSearch";
import { VariantSummary, stockLimit } from "../products/VariantSummary";
import { ReceiptPanel } from "../receipts/ReceiptPanel";
import { useMpesaExpress } from "./MpesaPrompt";
import { CheckoutPanel } from "./CheckoutPanel";
import { CustomerChooser, useCustomers } from "./CustomerChooser";
import { SaleSheet } from "./SaleSheet";
import "../admin/pos.css";
import "./posPage.css";
import { TextBox } from "../../components/forms/TextBox";

const ALL = "All";
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const groupOf = (p) => (p.product_type === "SERVICE" ? "Services" : p.category_name || "Uncategorised");
// Services last, the rest alphabetically.
const byGroup = (a, b) => (a === "Services" ? 1 : b === "Services" ? -1 : a.localeCompare(b));
// A steady colour per category, so the tiles are easy to tell apart at a glance.
const hue = (text) => [...text].reduce((sum, ch) => (sum * 31 + ch.charCodeAt(0)) % 360, 7);

// A product on the counter: one tap adds one more; the badge says how many are in the sale and − takes one off.
function Tile({ p, inCart, onAdd, onLess, user }) {
  const empty = stockLimit(p) < 1;
  const service = p.product_type === "SERVICE";
  return <article className={`posTile${inCart ? " inCart" : ""}`}>
    <button type="button" disabled={empty} onClick={() => onAdd(p)}>
      <span className="posTileMark" style={{ "--tile-hue": hue(groupOf(p)) }} aria-hidden="true">{p.product_name.slice(0, 1).toUpperCase()}</span>
      <span className="posTileName">{p.product_name}{p.variant_name && p.variant_name !== "Standard" ? <small> · {p.variant_name}</small> : null}</span>
      <span className="posTilePrice">{money(p.selling_price)}</span>
      <span className={`posTileStock${empty ? " out" : ""}`}>{service ? "Service" : empty ? "Out of stock" : `${Number(p.available).toLocaleString()} in stock`}</span>
      {inCart > 0 && <span className="posTileCount" aria-label={`${inCart} in the sale`}>{inCart}</span>}
    </button>
    {inCart > 0 && <button type="button" className="posTileLess" onClick={() => onLess(p)} aria-label={`One less ${p.product_name}`}><Minus size={16} /></button>}
    <ProductActions row={p} user={user} />
  </article>;
}

// A line of the sale: quantity with − and +, the agreed price (customers bargain) and its total.
function CartLine({ x, setLine, remove, canChangePrice, lineAmount }) {
  const limit = stockLimit(x.p);
  const floor = Number(x.p.minimum_price || 0);
  const asking = Number(x.p.selling_price);
  const price = Number(x.price ?? x.p.selling_price);
  const belowFloor = floor > 0 && price - Number(x.discount || 0) / x.q < floor;
  const given = (asking - price) * x.q;
  const bargain = canChangePrice || floor > 0;
  const step = (by) => setLine(x.p.id, { q: Math.min(limit, Math.max(1, x.q + by)), qText: undefined });
  return <article className="posLine">
    <div className="posLineHead">
      <b>{x.p.product_name}</b>
      <button type="button" className="posIconButton" onClick={() => remove(x.p.id)} aria-label={`Remove ${x.p.product_name}`}><X size={16} /></button>
    </div>
    <div className="posLineRow">
      <div className="posStepper">
        <button type="button" onClick={() => step(-1)} disabled={x.q <= 1} aria-label={`One less ${x.p.product_name}`}><Minus size={15} /></button>
        <input type="number" min="1" max={Number.isFinite(limit) ? limit : undefined} aria-label={`Quantity of ${x.p.product_name}`}
          // The box may be emptied while typing a new number; the sale keeps the last valid quantity.
          value={x.qText ?? x.q}
          onChange={(e) => {
            const text = e.target.value;
            const typed = Number(text);
            // More than is in stock shows the stock limit straight away.
            setLine(x.p.id, text.trim() === "" || !(typed >= 1) ? { qText: text }
              : typed > limit ? { qText: undefined, q: limit } : { qText: text, q: typed });
          }}
          onBlur={() => setLine(x.p.id, { qText: undefined })} />
        <button type="button" onClick={() => step(1)} disabled={x.q >= limit} aria-label={`One more ${x.p.product_name}`}><Plus size={15} /></button>
      </div>
      <span className="posLineEach">× {money(price)}</span>
      <strong className="posLineTotal">{money(lineAmount(x))}</strong>
    </div>
    {bargain && <div className="lineAdjust">
      <label className="agreedPrice">Price each
        <small>{floor > 0 ? `Bargain ${businessCurrency()} ${floor.toLocaleString()} – ${asking.toLocaleString()}` : `Asking ${businessCurrency()} ${asking.toLocaleString()}`}</small>
        <input type="number" step="0.01" inputMode="decimal" min="0" max={canChangePrice ? undefined : x.p.selling_price}
          value={x.price ?? x.p.selling_price} onChange={(e) => setLine(x.p.id, { price: e.target.value })}
          aria-label={`Agreed price for ${x.p.product_name}`} />
      </label>
      {given > 0 && !belowFloor && <small className="muted">{businessCurrency()} {given.toLocaleString()} off the asking price.</small>}
      {belowFloor && <p className="formNotice" role="status">Below the usual lowest price ({floor.toLocaleString()}). That's fine as long as
        it isn't below what the item cost; the sale is noted for the owner to review.</p>}
      {canChangePrice && <details className="lineDiscount" open={Number(x.discount || 0) > 0 || belowFloor || undefined}>
        <summary>Discount or reason</summary>
        <label>Line discount
          <input type="number" min="0" step="0.01" value={x.discount ?? ""} placeholder="0" onChange={(e) => setLine(x.p.id, { discount: e.target.value })} />
        </label>
        <label>Reason for the lower price
          <TextBox value={x.reason ?? ""} maxLength={160} onChange={(e) => setLine(x.p.id, { reason: e.target.value })} placeholder="e.g. loyal customer, damaged box" />
        </label>
      </details>}
    </div>}
  </article>;
}

// The sale just made: its total, the change to give, and its profit for those allowed to see it.
function SaleDone({ result, onReceipt, onNewSale }) {
  return <section className="posDone" aria-label="Sale complete">
    <header>
      <div>
        <b><CheckCircle2 size={18} aria-hidden="true" /> Sale complete · {result.receipt_number}</b>
        <p className="posDoneTotal">{money(result.total)}</p>
        {result.change > 0 && <p className="posChange">Give change: <b>{money(result.change)}</b></p>}
        {result.gross_profit !== undefined && (
          <p className={Number(result.gross_profit) < 0 ? "lossText" : "muted"}>
            {result.cost_pending ? "Profit not final: some stock has no buying price yet." : Number(result.gross_profit) < 0
              ? `LOSS of ${businessCurrency()} ${Math.abs(Number(result.gross_profit)).toFixed(2)} on this sale`
              : `Gross profit ${businessCurrency()} ${Number(result.gross_profit).toFixed(2)}`}
          </p>
        )}
      </div>
      <div className="posDoneActions">
        <button type="button" onClick={onReceipt}><Receipt size={16} aria-hidden="true" /> View &amp; send receipt</button>
        <button type="button" className="secondary" onClick={onNewSale}>New sale</button>
      </div>
    </header>
  </section>;
}

// The charged basket, read only, while the customer pays. A till reloaded mid-checkout has no basket, only its total.
function ChargedLines({ cart, checkout, lineAmount }) {
  if (!cart.length) return <p className="muted">{checkout.items} {checkout.items === 1 ? "line" : "lines"} · total {money(checkout.total)}</p>;
  return <ul className="posSummary">
    {cart.map((x) => <li key={x.p.id}>
      <span><b>{x.p.product_name}</b><small>{x.q} × {money(x.price ?? x.p.selling_price)}</small></span>
      <strong>{money(lineAmount(x))}</strong>
    </li>)}
    <li className="posSummaryTotal"><span>Total</span><strong>{money(checkout.total)}</strong></li>
  </ul>;
}

export function PosPage() {
  const { user } = useAuth();
  const express = useMpesaExpress();
  const saleRequest = useRef({ signature: null, key: null });
  const [saleBusy, setSaleBusy] = useState(false);
  const [customers, setCustomers] = useCustomers(user);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(ALL);
  const [rows, setRows] = useState([]);
  const [cart, setCart] = useState([]);
  const [result, setResult] = useState();
  const [showReceipt, setShowReceipt] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [discount, setDiscount] = useState("");
  const [discountReason, setDiscountReason] = useState("");
  // The basket charged and waiting for the customer to pay (see CheckoutPanel); nothing is sold until it is paid.
  const [checkout, setCheckout] = useState(null);
  const canChangePrice = user?.permissions?.includes("commerce.change_sale");
  const canSellAtLoss = user?.permissions?.includes("commerce.sell_below_cost");
  const [customerId, setCustomerId] = useState("");
  // The checkout window: closed (null), reviewing the sale, or showing the sale just made. Taking payment is shown
  // whenever a checkout is open.
  const [sheet, setSheet] = useState(null);
  const [lastAdded, setLastAdded] = useState("");
  const setLine = (id, changes) => setCart((c) => c.map((y) => (y.p.id === id ? { ...y, ...changes } : y)));
  const removeLine = (id) => setCart((c) => c.filter((y) => y.p.id !== id));
  // One less from a tile; the last one leaves the sale.
  const less = (p) => setCart((c) => c.flatMap((y) => (y.p.id !== p.id ? [y] : y.q > 1 ? [{ ...y, q: y.q - 1, qText: undefined }] : [])));
  // The sale's lines opened from the bar, to change quantities or remove items without leaving the products.
  const [showLines, setShowLines] = useState(false);
  // Line amount at the agreed price less its discount; this is what the customer is charged before any sale discount.
  const lineAmount = (x) => Math.max(0, Number(x.price ?? x.p.selling_price) * x.q - Number(x.discount || 0));
  const search = () =>
    api("/api/v1/commerce/pos/catalog/?q=" + encodeURIComponent(""))
      .then((data) => { setRows(data); setLoadError(""); })
      .catch((e) => setLoadError(e.message));
  useEffect(() => {
    void search();
    // A reloaded till picks up the cashier's own checkout that is still waiting for payment.
    api("/api/v1/commerce/pos/checkouts/").then((data) => {
      const mine = (data?.checkouts || []).find((row) => row.cashier_id === user?.id);
      if (mine) setCheckout(mine);
    }).catch(() => {});
  }, []);
  // Stock and prices change as others sell or receive: keep the till's list current (the cart is untouched).
  useLiveRefresh(search);
  const add = (p) => {
    setCart((old) => {
      const current = old.find((x) => x.p.id === p.id);
      if ((current?.q || 0) + 1 > stockLimit(p)) return old;
      return current ? old.map((x) => (x.p.id === p.id ? { ...x, p, q: x.q + 1, qText: undefined } : x)) : [...old, { p, q: 1 }];
    });
    setQuery("");
    setLastAdded(p.product_name);
  };
  const groups = useMemo(() => Object.entries(Object.groupBy(rows, groupOf)).sort(([a], [b]) => byGroup(a, b)), [rows]);
  const shown = category === ALL ? groups : groups.filter(([name]) => name === category);
  const counts = Object.fromEntries(cart.map((x) => [x.p.id, x.q]));
  const items = cart.reduce((sum, x) => sum + x.q, 0);
  const subtotal = cart.reduce((sum, x) => sum + lineAmount(x), 0);
  const total = Math.max(0, subtotal - Number(discount || 0));
  const clear = () => { setShowLines(false); setCart([]); setDiscount(""); setDiscountReason(""); setCustomerId(""); setError(""); setLastAdded(""); };
  const step = checkout ? "pay" : sheet;
  const openSheet = () => { if (cart.length) { setShowLines(false); setResult(undefined); setSheet("review"); } };
  const newSale = () => { setResult(undefined); setShowReceipt(false); setSheet(null); };
  // Marks the page as the till so the assistant's button shrinks to its icon and keeps clear of Complete sale.
  useEffect(() => {
    document.body.classList.add("posTill");
    return () => document.body.classList.remove("posTill");
  }, []);
    // F2 opens the checkout from anywhere on the till, as on most tills; scanners never send it.
  useEffect(() => {
    if (step) return undefined;
    const key = (event) => { if (event.key === "F2") { event.preventDefault(); openSheet(); } };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  });

  // Charging freezes the basket and its amount; the customer then pays on the checkout panel.
  const charge = async (e) => {
    e.preventDefault();
    if (saleBusy || !cart.length) return;
    const lines = cart.map((x) => ({ variant_id: x.p.id, quantity: x.q,
      ...(x.price !== undefined && x.price !== "" && Number(x.price) !== Number(x.p.selling_price) ? { unit_price: x.price } : {}),
      ...(Number(x.discount || 0) ? { discount: x.discount } : {}),
      ...(x.reason ? { discount_reason: x.reason } : {}) }));
    const terms = { discount: discount || 0, discount_reason: discountReason, ...(customerId ? { customer_id: customerId } : {}) };
    const signature = JSON.stringify({ terms, lines });
    if (saleRequest.current.signature !== signature) saleRequest.current = { signature, key: crypto.randomUUID() };
    setError("");
    setSaleBusy(true);
    const submit = (allowBelowCost) => api("/api/v1/commerce/pos/checkouts/", {
      method: "POST",
      body: JSON.stringify({ ...terms, items: lines, idempotency_key: saleRequest.current.key, ...(allowBelowCost ? { allow_below_cost: true } : {}) }),
    });
    try {
      let charged;
      try {
        charged = await submit(false);
      } catch (err) {
        // Selling below buying cost is allowed only for someone permitted to, after a clear warning.
        if (err.data?.code !== "below_cost" || !canSellAtLoss) throw err;
        const lines = [].concat(err.data.below_cost || []).join("\n");
        if (!(await confirmAction({ title: "Sell at a loss?", text: `${lines}\n\nThis sale will be recorded as a LOSS.`, confirmButtonText: "Sell at a loss" }))) return;
        charged = await submit(true);
      }
      setResult(undefined);
      setCheckout(charged);
    } catch (err) {
      setError(err.message);
    } finally { setSaleBusy(false); }
  };
  // Paid: the server made the sale. Show it like any finished sale and start the next one.
  const finished = async (done) => {
    const change = done.payments.reduce((sum, p) => sum + Number(p.change || 0), 0);
    setResult({ ...done.receipt, change });
    setCheckout(null);
    setSheet("done");
    saleRequest.current = { signature: null, key: null };
    clear();
    await search();
  };
  const backToBasket = ({ keepBasket }) => {
    setCheckout(null);
    saleRequest.current = { signature: null, key: null };
    setSheet(keepBasket ? "review" : null);
    if (!keepBasket) clear();
  };
  const customerPhone = customers.find((c) => String(c.id) === String(checkout?.customer_id || customerId))?.phone;

  return (
    <div className="posPage">
      <header className="posHeader">
        <div>
          <span className="eyebrow">Counter selling</span>
          <h1>Point of Sale</h1>
        </div>
        {express && <span className={`posExpressBadge${express.till_notices || express.ready ? " on" : ""}`}>
          <Smartphone size={15} aria-hidden="true" /> {express.till_notices ? "Till payments checked with Safaricom" : express.ready ? "M-Pesa prompts on" : "M-Pesa by code"}
        </span>}
      </header>
      {result && step !== "done" && <SaleDone result={result} onReceipt={() => setShowReceipt(true)} onNewSale={newSale} />}
      {showReceipt && result && <ReceiptPanel saleId={result.sale_id} onClose={() => setShowReceipt(false)} />}
      {loadError && <FormError title="Could not load products." message={loadError} />}
      <section className="posCatalog" aria-label="Products">
        <ProductSearch value={query} onChange={setQuery} endpoint="/api/v1/commerce/pos/catalog/" minLength={1} limit={50} onSelect={add}
          exactScan isDisabled={(p) => stockLimit(p) < 1} renderResult={(p) => <VariantSummary row={p} />}
          renderActions={(p) => <ProductActions row={p} user={user} />} placeholder="Scan a barcode or type a name or item code" />
        {!query.trim() && groups.length > 1 && <div className="posChips" role="group" aria-label="Categories">
          {[ALL, ...groups.map(([name]) => name)].map((name) => (
            <button type="button" key={name} aria-pressed={category === name} onClick={() => setCategory(name)}>{name}</button>
          ))}
        </div>}
        {!query.trim() && shown.map(([name, products]) => (
          <section key={name} className="posGroup">
            <h2>{name}</h2>
            <div className="posTiles">
              {products.map((p) => <Tile key={p.id} p={p} inCart={counts[p.id] || 0} onAdd={add} onLess={less} user={user} />)}
            </div>
          </section>
        ))}
      </section>

      {/* The sale so far, always in view while products are picked; the checkout opens only when asked for. */}
      <div className={`posSaleBar${cart.length ? "" : " empty"}`} role="region" aria-label="Sale so far">
        {showLines && cart.length > 0 && <div className="posSaleBarLines" id="pos-bar-lines">
          <div className="posCartHead">
            <h3>Current sale</h3>
            <button type="button" className="posIconButton" onClick={clear} aria-label="Clear the sale"><Trash2 size={16} /></button>
          </div>
          <div className="posLines">
            {cart.map((x) => <CartLine key={x.p.id} x={x} setLine={setLine} remove={removeLine} canChangePrice={canChangePrice} lineAmount={lineAmount} />)}
          </div>
        </div>}
        <span className="posSaleBarIcon" aria-hidden="true"><ShoppingCart size={20} /></span>
        {cart.length ? <button type="button" className="posSaleBarInfo posSaleBarItems" onClick={() => setShowLines((open) => !open)}
          aria-expanded={showLines} aria-controls="pos-bar-lines">
          <b key={items} className="posSaleBarCount">{items} {items === 1 ? "item" : "items"} <span className="posSaleBarEdit">· {showLines ? "Hide" : "Change"} <ChevronDown size={15} aria-hidden="true" /></span></b>
          {lastAdded && <small>Added {lastAdded}</small>}
        </button> : <span className="posSaleBarInfo"><small>Tap products or scan a barcode to start a sale.</small></span>}
        {cart.length > 0 && <strong className="posSaleBarTotal">{money(total)}</strong>}
        <button type="button" className="posSaleBarGo" disabled={!cart.length} onClick={openSheet}>
          Complete sale <kbd aria-hidden="true">F2</kbd>
        </button>
      </div>

      {step && <SaleSheet step={step} onClose={step === "pay" || showReceipt ? undefined : step === "done" ? newSale : () => setSheet(null)}>
        {step === "review" && <form className="posSheetBody" onSubmit={charge}>
          <section className="posSheetMain" aria-labelledby="pos-lines-title">
            <div className="posCartHead">
              <h3 id="pos-lines-title">Current sale</h3>
              {cart.length > 0 && <>
                <span className="posCount">{items} {items === 1 ? "item" : "items"}</span>
                <button type="button" className="posIconButton" onClick={clear} aria-label="Clear the sale"><Trash2 size={16} /></button>
              </>}
            </div>
            <div className="posLines">
              {!cart.length ? <Empty>The sale is empty. Go back to the products to add some.</Empty>
                : cart.map((x) => <CartLine key={x.p.id} x={x} setLine={setLine} remove={removeLine} canChangePrice={canChangePrice} lineAmount={lineAmount} />)}
            </div>
          </section>
          <aside className="posSheetSide">
            <div className="posTotals">
              <div><span>Subtotal</span><span>{money(subtotal)}</span></div>
              <details className="posSaleDiscount" open={Number(discount || 0) > 0 || undefined}>
                <summary>Discount on the whole sale{Number(discount || 0) > 0 ? ` · −${money(discount)}` : ""}</summary>
                <label>Discount on the whole sale
                  <input name="discount" type="number" min="0" step="0.01" value={discount} placeholder="0" onChange={(e) => setDiscount(e.target.value)} />
                </label>
                <label>Reason for sale discount<TextBox name="discount_reason" maxLength={160} value={discountReason} onChange={(e) => setDiscountReason(e.target.value)} /></label>
              </details>
              <div className="posGrandTotal"><span>Total</span><strong>{money(total)}</strong></div>
            </div>
            <CustomerChooser user={user} customers={customers} setCustomers={setCustomers} value={customerId} onChange={setCustomerId} />
            <FormError title="Could not charge the sale." message={error} />
            <div className="posSheetActions">
              <button className="posCharge" disabled={!cart.length || saleBusy}>
                <span>{saleBusy ? "Charging…" : "Charge"}</span>
                {!saleBusy && cart.length > 0 && <strong>{money(total)}</strong>}
              </button>
              <button type="button" className="secondary" onClick={() => setSheet(null)}><ArrowLeft size={16} aria-hidden="true" /> Add more products</button>
            </div>
          </aside>
        </form>}
        {step === "pay" && <div className="posSheetBody">
          <section className="posSheetMain" aria-labelledby="pos-charged-title">
            <h3 id="pos-charged-title">Items</h3>
            <ChargedLines cart={cart} checkout={checkout} lineAmount={lineAmount} />
          </section>
          <aside className="posSheetSide">
            <CheckoutPanel checkout={checkout} express={express} customerPhone={customerPhone} onChange={setCheckout}
              onDone={finished} onBack={backToBasket}
              user={user} customers={customers} setCustomers={setCustomers} />
          </aside>
        </div>}
        {step === "done" && result && <div className="posSheetDone">
          <SaleDone result={result} onReceipt={() => setShowReceipt(true)} onNewSale={newSale} />
        </div>}
      </SaleSheet>}
    </div>
  );
}
