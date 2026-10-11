import { useEffect, useMemo, useRef, useState } from "react";
import { Banknote, CreditCard, Landmark, Minus, Plus, Receipt, ShoppingCart, Smartphone, Trash2, X } from "lucide-react";
import { businessCurrency } from "../../core/organization/presentation";
import { label } from "../../core/ui/labels";
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
import { PromptStatus, SendPrompt, shownPhone, useMpesaExpress, usePrompt } from "./MpesaPrompt";
import "../admin/pos.css";
import "./posPage.css";

const ALL = "All";
const METHODS = [
  { id: "CASH", name: "Cash", icon: Banknote },
  { id: "MPESA", name: "M-Pesa", icon: Smartphone },
  { id: "BANK", name: "Bank", icon: Landmark },
  { id: "OTHER", name: "Other", icon: CreditCard },
];
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const groupOf = (p) => (p.product_type === "SERVICE" ? "Services" : p.category_name || "Uncategorised");
// Services last, the rest alphabetically.
const byGroup = (a, b) => (a === "Services" ? 1 : b === "Services" ? -1 : a.localeCompare(b));
// A steady colour per category, so the tiles are easy to tell apart at a glance.
const hue = (text) => [...text].reduce((sum, ch) => (sum * 31 + ch.charCodeAt(0)) % 360, 7);

// A product on the counter: one tap adds one more; the badge says how many are in the sale.
function Tile({ p, inCart, onAdd, user }) {
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
          <input value={x.reason ?? ""} maxLength={160} onChange={(e) => setLine(x.p.id, { reason: e.target.value })} placeholder="e.g. loyal customer, damaged box" />
        </label>
      </details>}
    </div>}
  </article>;
}

// What happened to the sale just recorded: its total, change, profit, and the M-Pesa payment until it is confirmed.
function SaleDone({ result, setResult, express, canConfirmPayment, onReceipt, onNewSale }) {
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState("");
  const [sent, setSent] = useState(result.prompt);
  // Paid on the phone: the server confirmed the payment with the M-Pesa code.
  const prompt = usePrompt(sent, (done) => {
    if (done.status === "COMPLETED" && !done.detail?.includes("could not be confirmed")) setResult((r) => ({ ...r, waiting_payment: undefined, confirmed_reference: done.receipt_number }));
  });
  const waiting = result.waiting_payment;
  // M-Pesa taken at the till waits until someone checks the money arrived and enters its code.
  const confirmPayment = async (e) => {
    e.preventDefault();
    if (confirmBusy) return;
    const reference = String(new FormData(e.currentTarget).get("reference") || "").trim();
    setConfirmBusy(true); setConfirmError("");
    try {
      await api(`/api/v1/commerce/payments/${waiting.id}/confirm/`, { method: "POST", body: JSON.stringify({ reference }) });
      setResult((r) => ({ ...r, waiting_payment: undefined, confirmed_reference: reference }));
    } catch (err) {
      setConfirmError(err.message);
    } finally { setConfirmBusy(false); }
  };
  const canPrompt = express?.ready && waiting?.method === "MPESA";
  const pending = prompt?.status === "PENDING";
  return <section className="posDone" aria-label="Sale complete">
    <header>
      <div>
        <b>Sale complete · {result.receipt_number}</b>
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
    {(prompt || result.prompt_error) && <div className="posPromptBox">
      <PromptStatus prompt={prompt} />
      {result.prompt_error && !prompt && <p className="mpesaPrompt failed" role="status"><span><b>The prompt was not sent.</b> {result.prompt_error}</span></p>}
    </div>}
    {waiting && <div className="paymentConfirm" role="group" aria-label="Confirm M-Pesa payment">
      <p className="formNotice" role="status">{label(waiting.method)} {businessCurrency()} {Number(waiting.amount).toLocaleString()} is waiting for
        confirmation. It is not counted as received until it is confirmed.</p>
      {canPrompt && !pending && <SendPrompt paymentId={waiting.id} defaultPhone={shownPhone(prompt?.phone || result.mpesa_phone)}
        label={prompt ? "Send the prompt again" : "Send M-Pesa prompt"} onSent={setSent} />}
      {canConfirmPayment ? <form onSubmit={confirmPayment} className="manualConfirm">
        <label>{canPrompt ? "Or enter the M-Pesa code from the confirmation message" : "M-Pesa code from the confirmation message"}
          <input name="reference" required maxLength={120} defaultValue={waiting.reference || ""} />
        </label>
        <button className={canPrompt ? "secondary" : undefined} disabled={confirmBusy}>{confirmBusy ? "Confirming…" : "Confirm money received"}</button>
        <FormError title="Could not confirm the payment." message={confirmError} />
      </form> : !canPrompt && <p className="muted">Ask someone allowed to confirm payments to confirm it under Sales.</p>}
    </div>}
    {result.confirmed_reference && <p role="status" className="posConfirmed">Payment confirmed ({result.confirmed_reference}).</p>}
  </section>;
}

export function PosPage() {
  const { user } = useAuth();
  const express = useMpesaExpress();
  const saleRequest = useRef({ signature: null, key: null });
  const [saleBusy, setSaleBusy] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(ALL);
  const [rows, setRows] = useState([]);
  const [cart, setCart] = useState([]);
  const [result, setResult] = useState();
  const [showReceipt, setShowReceipt] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [method, setMethod] = useState("CASH");
  const [cashGiven, setCashGiven] = useState("");
  const [mpesaPhone, setMpesaPhone] = useState("");
  const [discount, setDiscount] = useState("");
  const canChangePrice = user?.permissions?.includes("commerce.change_sale");
  const canSellAtLoss = user?.permissions?.includes("commerce.sell_below_cost");
  const canAddCustomer = user?.permissions?.includes("accounts.add_customerprofile");
  const canConfirmPayment = user?.permissions?.includes("commerce.change_payment");
  const [customerId, setCustomerId] = useState("");
  const [newCustomer, setNewCustomer] = useState(null);
  const [customerError, setCustomerError] = useState("");
  const cartRef = useRef(null);
  // Someone who pays later must be named, so the balance is owed by a real customer.
  const addCustomer = async () => {
    setCustomerError("");
    try {
      const created = await api("/api/v1/commerce/customers/", { method: "POST", body: JSON.stringify({ name: newCustomer.name.trim(), phone: newCustomer.phone.trim() }) });
      setCustomers((list) => [created, ...list]);
      chooseCustomer(String(created.id), created);
      setNewCustomer(null);
    } catch (e) {
      setCustomerError(e.message);
    }
  };
  // A named customer's phone is the obvious number to prompt.
  const chooseCustomer = (id, known) => {
    setCustomerId(id);
    const phone = (known || customers.find((c) => String(c.id) === id))?.phone;
    if (phone && !mpesaPhone) setMpesaPhone(phone);
  };
  const setLine = (id, changes) => setCart((c) => c.map((y) => (y.p.id === id ? { ...y, ...changes } : y)));
  const removeLine = (id) => setCart((c) => c.filter((y) => y.p.id !== id));
  // Line amount at the agreed price less its discount; this is what the customer is charged before any sale discount.
  const lineAmount = (x) => Math.max(0, Number(x.price ?? x.p.selling_price) * x.q - Number(x.discount || 0));
  const search = () =>
    api("/api/v1/commerce/pos/catalog/?q=" + encodeURIComponent(""))
      .then((data) => { setRows(data); setLoadError(""); })
      .catch((e) => setLoadError(e.message));
  useEffect(() => {
    void search();
    if (user?.permissions?.includes("accounts.view_customerprofile")) api("/api/v1/commerce/customers/").then(setCustomers).catch(() => {});
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
  };
  const groups = useMemo(() => Object.entries(Object.groupBy(rows, groupOf)).sort(([a], [b]) => byGroup(a, b)), [rows]);
  const shown = category === ALL ? groups : groups.filter(([name]) => name === category);
  const counts = Object.fromEntries(cart.map((x) => [x.p.id, x.q]));
  const items = cart.reduce((sum, x) => sum + x.q, 0);
  const subtotal = cart.reduce((sum, x) => sum + lineAmount(x), 0);
  const total = Math.max(0, subtotal - Number(discount || 0));
  const change = method === "CASH" && cashGiven !== "" ? Number(cashGiven) - total : null;
  const prompting = method === "MPESA" && express?.ready;
  const clear = () => { setCart([]); setDiscount(""); setCashGiven(""); setMpesaPhone(""); setCustomerId(""); setError(""); };

  const complete = async (e) => {
    e.preventDefault();
    if (saleBusy || !cart.length) return;
    const form = Object.fromEntries(new FormData(e.currentTarget));
    const promptPhone = prompting ? mpesaPhone.trim() : "";
    if (!(await confirmAction({
      title: "Complete this sale?",
      text: `Charge ${businessCurrency()} ${total.toFixed(2)} and update stock?${promptPhone ? ` An M-Pesa prompt goes to ${promptPhone}.` : ""}`,
      confirmButtonText: "Complete sale",
    }))) return;
    const lines = cart.map((x) => ({ variant_id: x.p.id, quantity: x.q,
      ...(x.price !== undefined && x.price !== "" && Number(x.price) !== Number(x.p.selling_price) ? { unit_price: x.price } : {}),
      ...(Number(x.discount || 0) ? { discount: x.discount } : {}),
      ...(x.reason ? { discount_reason: x.reason } : {}) }));
    const signature = JSON.stringify({ ...form, lines, promptPhone });
    if (saleRequest.current.signature !== signature) saleRequest.current = { signature, key: crypto.randomUUID() };
    setError("");
    setSaleBusy(true);
    const submit = (allowBelowCost) => api("/api/v1/commerce/pos/complete/", {
      method: "POST",
      body: JSON.stringify({ ...form, items: lines, idempotency_key: saleRequest.current.key,
        ...(promptPhone ? { mpesa_phone: promptPhone } : {}), ...(allowBelowCost ? { allow_below_cost: true } : {}) }),
    });
    try {
      let sale;
      try {
        sale = await submit(false);
      } catch (err) {
        // Selling below buying cost is allowed only for someone permitted to, after a clear warning.
        if (err.data?.code !== "below_cost" || !canSellAtLoss) throw err;
        const lines = [].concat(err.data.below_cost || []).join("\n");
        if (!(await confirmAction({ title: "Sell at a loss?", text: `${lines}\n\nThis sale will be recorded as a LOSS.`, confirmButtonText: "Sell at a loss" }))) return;
        sale = await submit(true);
      }
      setResult({ ...sale, change: change > 0 ? change : 0, mpesa_phone: promptPhone });
      saleRequest.current = { signature: null, key: null };
      clear();
      window.scrollTo?.({ top: 0, behavior: "smooth" });
      await search();
    } catch (err) {
      setError(err.message);
    } finally { setSaleBusy(false); }
  };

  return (
    <div className="posPage">
      <header className="posHeader">
        <div>
          <span className="eyebrow">Counter selling</span>
          <h1>Point of Sale</h1>
        </div>
        {express && <span className={`posExpressBadge${express.ready ? " on" : ""}`}>
          <Smartphone size={15} aria-hidden="true" /> {express.ready ? "M-Pesa prompts on" : "M-Pesa by code"}
        </span>}
      </header>
      {result && <SaleDone result={result} setResult={setResult} express={express} canConfirmPayment={canConfirmPayment}
        onReceipt={() => setShowReceipt(true)} onNewSale={() => setResult(undefined)} />}
      {showReceipt && result && <ReceiptPanel saleId={result.sale_id} onClose={() => setShowReceipt(false)} />}
      {loadError && <FormError title="Could not load products." message={loadError} />}
      <div className="posLayout">
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
                {products.map((p) => <Tile key={p.id} p={p} inCart={counts[p.id] || 0} onAdd={add} user={user} />)}
              </div>
            </section>
          ))}
        </section>

        <form className="posCart" onSubmit={complete} ref={cartRef}>
          <div className="posCartHead">
            <h2>Current sale</h2>
            {cart.length > 0 && <>
              <span className="posCount">{items} {items === 1 ? "item" : "items"}</span>
              <button type="button" className="posIconButton" onClick={clear} aria-label="Clear the sale"><Trash2 size={16} /></button>
            </>}
          </div>
          <div className="posLines">
            {!cart.length ? <Empty>Tap products to add them, or scan a barcode.</Empty>
              : cart.map((x) => <CartLine key={x.p.id} x={x} setLine={setLine} remove={removeLine} canChangePrice={canChangePrice} lineAmount={lineAmount} />)}
          </div>

          <div className="posTotals">
            <div><span>Subtotal</span><span>{money(subtotal)}</span></div>
            <details className="posSaleDiscount" open={Number(discount || 0) > 0 || undefined}>
              <summary>Discount on the whole sale{Number(discount || 0) > 0 ? ` · −${money(discount)}` : ""}</summary>
              <label>Discount on the whole sale
                <input name="discount" type="number" min="0" step="0.01" value={discount} placeholder="0" onChange={(e) => setDiscount(e.target.value)} />
              </label>
              <label>Reason for sale discount<input name="discount_reason" maxLength={160} /></label>
            </details>
            <div className="posGrandTotal"><span>Total</span><strong>{money(total)}</strong></div>
          </div>

          <fieldset className="posMethods">
            <legend>Payment</legend>
            {METHODS.map(({ id, name, icon: Icon }) => (
              <label key={id} className={method === id ? "on" : ""}>
                <input type="radio" name="payment_method" value={id} checked={method === id} onChange={() => setMethod(id)} />
                <Icon size={18} aria-hidden="true" /> {name}
              </label>
            ))}
          </fieldset>
          {method === "CASH" && <div className="posPayDetail">
            <label>Cash received
              <input type="number" min="0" step="0.01" inputMode="decimal" value={cashGiven} onChange={(e) => setCashGiven(e.target.value)} placeholder={total ? total.toFixed(2) : "0"} />
            </label>
            {change !== null && (change >= 0 ? <p className="posChange">Change: <b>{money(change)}</b></p>
              : <p className="formNotice" role="status">{money(-change)} short. Take the rest, or record it as a part payment below.</p>)}
          </div>}
          {method === "MPESA" && <div className="posPayDetail">
            {prompting ? <>
              <label>Customer's M-Pesa number
                <input value={mpesaPhone} onChange={(e) => setMpesaPhone(e.target.value)} inputMode="tel" placeholder="0712 345 678" maxLength={16} />
              </label>
              <p className="muted">{mpesaPhone.trim() ? "When you complete the sale, the customer gets a prompt on this phone to enter their M-Pesa PIN." : "Enter the number to send a prompt, or leave it empty to enter the M-Pesa code yourself."}</p>
            </> : <p className="muted">Take the payment on your till, then enter the code from the M-Pesa message.{express?.can_change ? " To send prompts to customers' phones, set up M-Pesa payments in Settings." : ""}</p>}
            {!mpesaPhone.trim() || !prompting ? <label>M-Pesa code (optional)<input name="payment_reference" maxLength={100} placeholder="e.g. SJK4H7XQ2P" /></label> : null}
          </div>}
          {(method === "BANK" || method === "OTHER") && <div className="posPayDetail">
            <label>Payment reference<input name="payment_reference" maxLength={100} /></label>
          </div>}

          <details className="posCredit"><summary>Credit sale or partial payment</summary>
            <p className="muted">Leave amount blank for full payment. Enter zero for credit. Unconfirmed mobile money is not counted as received.</p>
            <label>Customer (needed if anything is left to pay)<select name="customer_id" value={customerId} onChange={(e) => chooseCustomer(e.target.value)}><option value="">Walk-in customer</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name} {c.phone}</option>)}</select></label>
            {canAddCustomer && (newCustomer ? <div className="inlineCreate" role="group" aria-label="New customer">
              <label>Customer name<input value={newCustomer.name} maxLength={150} onChange={(e) => setNewCustomer({ ...newCustomer, name: e.target.value })} /></label>
              <label>Phone<input value={newCustomer.phone} maxLength={30} inputMode="tel" onChange={(e) => setNewCustomer({ ...newCustomer, phone: e.target.value })} /></label>
              <button type="button" disabled={!newCustomer.name.trim()} onClick={() => void addCustomer()}>Save customer</button>
              <button type="button" className="secondary" onClick={() => { setNewCustomer(null); setCustomerError(""); }}>Cancel</button>
              <FormError title="Could not add the customer." message={customerError} />
            </div> : <button type="button" className="secondary" onClick={() => setNewCustomer({ name: "", phone: "" })}>+ New customer</button>)}
            <label>Amount paid now<input name="paid_amount" type="number" min="0" step="0.01" /></label>
            <label>Balance due date<input name="due_date" type="date" /></label>
          </details>

          <button className="posCharge" disabled={!cart.length || saleBusy}>
            <span>{saleBusy ? "Recording…" : prompting && mpesaPhone.trim() ? "Complete sale & send prompt" : "Complete sale"}</span>
            {!saleBusy && cart.length > 0 && <strong>{money(total)}</strong>}
          </button>
          <FormError title="Could not complete the sale." message={error} />
        </form>
      </div>
      {cart.length > 0 && <button type="button" className="posMobileBar" onClick={() => cartRef.current?.scrollIntoView({ behavior: "smooth" })}>
        <ShoppingCart size={18} aria-hidden="true" /> {items} {items === 1 ? "item" : "items"} · <strong>{money(total)}</strong><span>Review sale</span>
      </button>}
    </div>
  );
}
