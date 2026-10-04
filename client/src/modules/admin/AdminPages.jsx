import { businessCurrency } from "../../core/organization/presentation";
import { label } from "../../core/ui/labels";
import { useAuth } from "../../core/auth/AuthContext";
import { ProductActions } from "../products/ProductActions";
import "./pos.css";
import { ProductSearch } from "../storefront/components/ProductSearch";
import { VariantSummary, stockLimit } from "../products/VariantSummary";
import { AdjustmentReport } from "../inventory/StockAdjustmentPage";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { ReceiptPanel } from "../receipts/ReceiptPanel";
import { useEffect, useRef, useState } from "react";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
import { confirmAction } from "../../core/ui/alerts";
import { DashboardPage } from "./DashboardPage";
import { useLiveRefresh } from "../../core/data/liveRefresh";
export { DashboardPage };
function useLoad(url) {
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const load = () =>
    api(url)
      .then(setData)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, [url]);
  useLiveRefresh(load);
  return { data, error, load };
}
export function PosPage() {
  const { user } = useAuth();
  const saleRequest = useRef({ signature: null, key: null });
  const [saleBusy, setSaleBusy] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [cart, setCart] = useState([]);
  const [result, setResult] = useState();
  const [showReceipt, setShowReceipt] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const canChangePrice = user?.permissions?.includes("commerce.change_sale");
  const canSellAtLoss = user?.permissions?.includes("commerce.sell_below_cost");
  const canAddCustomer = user?.permissions?.includes("accounts.add_customerprofile");
  const canConfirmPayment = user?.permissions?.includes("commerce.change_payment");
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState("");
  // M-Pesa taken at the till waits until someone checks the money arrived and enters its code.
  const confirmPayment = async (e) => {
    e.preventDefault();
    if (confirmBusy) return;
    const reference = String(new FormData(e.currentTarget).get("reference") || "").trim();
    setConfirmBusy(true);
    setConfirmError("");
    try {
      await api(`/api/v1/commerce/payments/${result.waiting_payment.id}/confirm/`, { method: "POST", body: JSON.stringify({ reference }) });
      setResult((r) => ({ ...r, waiting_payment: undefined, confirmed_reference: reference }));
    } catch (err) {
      setConfirmError(err.message);
    } finally { setConfirmBusy(false); }
  };
  const [customerId, setCustomerId] = useState("");
  const [newCustomer, setNewCustomer] = useState(null);
  const [customerError, setCustomerError] = useState("");
  // Someone who pays later must be named, so the balance is owed by a real customer.
  const addCustomer = async () => {
    setCustomerError("");
    try {
      const created = await api("/api/v1/commerce/customers/", { method: "POST", body: JSON.stringify({ name: newCustomer.name.trim(), phone: newCustomer.phone.trim() }) });
      setCustomers((rows) => [created, ...rows]);
      setCustomerId(String(created.id));
      setNewCustomer(null);
    } catch (e) {
      setCustomerError(e.message);
    }
  };
  const setLine = (id, changes) => setCart((c) => c.map((y) => (y.p.id === id ? { ...y, ...changes } : y)));
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
      return current
        ? old.map((x) => (x.p.id === p.id ? { p, q: x.q + 1 } : x))
        : [...old, { p, q: 1 }];
    });
    setQuery("");
  };
  const groups = Object.groupBy(rows, (p) =>
    p.product_type === "SERVICE"
      ? "Services"
      : p.category_name || "Uncategorised",
  );
  const complete = async (e) => {
    e.preventDefault();
    if (saleBusy) return;
    const form = Object.fromEntries(new FormData(e.currentTarget));
    if (
      !(await confirmAction({
        title: "Complete this sale?",
        text: `Charge ${businessCurrency()} ${(cart.reduce((sum, item) => sum + lineAmount(item), 0) - Number(form.discount || 0)).toFixed(2)} and update stock?`,
        confirmButtonText: "Complete sale",
      }))
    )
      return;
    const items = cart.map((x) => ({ variant_id: x.p.id, quantity: x.q,
      ...(x.price !== undefined && x.price !== "" && Number(x.price) !== Number(x.p.selling_price) ? { unit_price: x.price } : {}),
      ...(Number(x.discount || 0) ? { discount: x.discount } : {}),
      ...(x.reason ? { discount_reason: x.reason } : {}) }));
    const signature = JSON.stringify({ ...form, items });
    if (saleRequest.current.signature !== signature) saleRequest.current = { signature, key:crypto.randomUUID() };
    setError("");
    setSaleBusy(true);
    const submit = (allowBelowCost) => api("/api/v1/commerce/pos/complete/", {
      method: "POST",
      body: JSON.stringify({ ...form, items, idempotency_key: saleRequest.current.key, ...(allowBelowCost ? { allow_below_cost: true } : {}) }),
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
      setResult(sale);
      setConfirmError("");
      saleRequest.current = { signature:null, key:null };
      setCart([]);
      setCustomerId("");
      await search();
    } catch (err) {
      setError(err.message);
    } finally { setSaleBusy(false); }
  };
  return (
    <>
      <span className="eyebrow">Counter selling</span>
      <h1>Point of Sale</h1>
      {result && (
        <div className="callout receipt">
          <div>
            <b>Sale complete · {result.receipt_number}</b>
            <p>Total {businessCurrency()} {result.total}</p>
            {result.gross_profit !== undefined && (
              <p className={Number(result.gross_profit) < 0 ? "lossText" : "muted"}>
                {result.cost_pending ? "Profit not final: some stock has no buying price yet." : Number(result.gross_profit) < 0
                  ? `LOSS of ${businessCurrency()} ${Math.abs(Number(result.gross_profit)).toFixed(2)} on this sale`
                  : `Gross profit ${businessCurrency()} ${Number(result.gross_profit).toFixed(2)}`}
              </p>
            )}
            {result.waiting_payment && <div className="paymentConfirm" role="group" aria-label="Confirm M-Pesa payment">
              <p className="formNotice" role="status">{label(result.waiting_payment.method)} {businessCurrency()} {Number(result.waiting_payment.amount).toLocaleString()} is waiting for
                confirmation. It is not counted as received until it is confirmed.</p>
              {canConfirmPayment ? <form onSubmit={confirmPayment}>
                <label>M-Pesa code from the confirmation message
                  <input name="reference" required maxLength={120} defaultValue={result.waiting_payment.reference || ""} />
                </label>
                <button disabled={confirmBusy}>{confirmBusy ? "Confirming…" : "Confirm money received"}</button>
                <FormError title="Could not confirm the payment." message={confirmError} />
              </form> : <p className="muted">Ask someone allowed to confirm payments to confirm it under Sales.</p>}
            </div>}
            {result.confirmed_reference && <p role="status">Payment confirmed ({result.confirmed_reference}).</p>}
          </div>
          <button onClick={() => setShowReceipt(true)}>View &amp; send receipt</button>
        </div>
      )}
      {showReceipt && result && <ReceiptPanel saleId={result.sale_id} onClose={() => setShowReceipt(false)} />}
      {loadError && <FormError title="Could not load products." message={loadError} />}
      <div className="posGrid">
        <section>
          <ProductSearch
            value={query}
            onChange={setQuery}
            endpoint="/api/v1/commerce/pos/catalog/"
            minLength={1}
            limit={50}
            onSelect={add}
            exactScan
            isDisabled={(p) => stockLimit(p) < 1}
            renderResult={(p) => <VariantSummary row={p} />}
            renderActions={(p) => <ProductActions row={p} user={user} />}
            placeholder="Scan a barcode or type a name or item code"
          />
          {!query.trim() &&
            Object.entries(groups)
              .sort(([a], [b]) =>
                a === "Services"
                  ? 1
                  : b === "Services"
                    ? -1
                    : a.localeCompare(b),
              )
              .map(([category, products]) => (
                <section key={category}>
                  <h2>{category}</h2>
                  <div className="posCatalogue">
                    {products.map((p) => (
                      <article key={p.id}>
                        <button
                          disabled={stockLimit(p) < 1}
                          onClick={() => add(p)}
                        >
                          <VariantSummary row={p} />
                        </button>
                        <ProductActions row={p} user={user} />
                      </article>
                    ))}
                  </div>
                </section>
              ))}
        </section>
        <form className="saleCart" onSubmit={complete}>
          <h2>Current sale</h2>
          {!cart.length ? (
            <Empty>Scan or select an item.</Empty>
          ) : (
            cart.map((x) => (
              <article key={x.p.id}>
                <b>{x.p.product_name}</b>
                <input
                  type="number"
                  min="1"
                  max={
                    Number.isFinite(stockLimit(x.p))
                      ? stockLimit(x.p)
                      : undefined
                  }
                  aria-label={`Quantity of ${x.p.product_name}`}
                  // The box may be emptied while typing a new number; the sale keeps the last valid quantity.
                  value={x.qText ?? x.q}
                  onChange={(e) => {
                    const text = e.target.value;
                    const typed = Number(text);
                    // More than is in stock shows the stock limit straight away.
                    setLine(x.p.id, text.trim() === "" || !(typed >= 1) ? { qText: text }
                      : typed > stockLimit(x.p) ? { qText: undefined, q: stockLimit(x.p) }
                      : { qText: text, q: typed });
                  }}
                  onBlur={() => setLine(x.p.id, { qText: undefined })}
                />
                <span>{businessCurrency()} {lineAmount(x).toFixed(2)}</span>
                {(canChangePrice || Number(x.p.minimum_price) > 0) && (() => {
                  // Customers bargain: any price up to the asking price. The server refuses one below what the item cost.
                  const floor = Number(x.p.minimum_price || 0);
                  const asking = Number(x.p.selling_price);
                  const price = Number(x.price ?? x.p.selling_price);
                  const belowFloor = floor > 0 && price - Number(x.discount || 0) / x.q < floor;
                  const given = (asking - price) * x.q;
                  return <div className="lineAdjust">
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
                  </div>;
                })()}
              </article>
            ))
          )}
          <FormField
            label="Discount on the whole sale"
            name="discount"
            type="number"
            defaultValue="0"
          />
          <FormField label="Reason for sale discount" name="discount_reason" maxLength={160} />
          <label>
            Payment
            <select name="payment_method">
              <option value="CASH">Cash</option>
              <option value="MPESA">Lipa na M-Pesa (till)</option>
              <option value="BANK">Bank</option>
              <option value="OTHER">Other</option>
            </select>
          </label>
          <FormField label="Payment reference" name="payment_reference" />
          <details><summary>Credit sale or partial payment</summary><p>Leave amount blank for full payment. Enter zero for credit. Unconfirmed mobile money is not counted as received.</p>
          <label>Customer (needed if anything is left to pay)<select name="customer_id" value={customerId} onChange={(e) => setCustomerId(e.target.value)}><option value="">Walk-in customer</option>{customers.map(c => <option key={c.id} value={c.id}>{c.name} {c.phone}</option>)}</select></label>
          {canAddCustomer && (newCustomer ? <div className="inlineCreate" role="group" aria-label="New customer">
            <label>Customer name<input value={newCustomer.name} maxLength={150} onChange={(e) => setNewCustomer({ ...newCustomer, name: e.target.value })} /></label>
            <label>Phone<input value={newCustomer.phone} maxLength={30} inputMode="tel" onChange={(e) => setNewCustomer({ ...newCustomer, phone: e.target.value })} /></label>
            <button type="button" disabled={!newCustomer.name.trim()} onClick={() => void addCustomer()}>Save customer</button>
            <button type="button" className="secondary" onClick={() => { setNewCustomer(null); setCustomerError(""); }}>Cancel</button>
            <FormError title="Could not add the customer." message={customerError} />
          </div> : <button type="button" className="secondary" onClick={() => setNewCustomer({ name: "", phone: "" })}>+ New customer</button>)}
          <FormField label="Amount paid now" name="paid_amount" type="number" min="0" step="0.01" />
          <FormField label="Balance due date" name="due_date" type="date" />
          </details>
          <button disabled={!cart.length || saleBusy}>{saleBusy ? "Recording…" : "Complete sale"}</button>
          <FormError title="Could not complete the sale." message={error} />
        </form>
      </div>
    </>
  );
}
export function StaffOrdersPage() {
  const { data, error, load } = useLoad("/api/v1/commerce/staff/orders/");
  if (error) return <ErrorState message={error} retry={load} />;
  if (!data) return <Loading />;
  const complete = async (o) => {
    if (
      !(await confirmAction({
        title: `Complete order ${o.number}?`,
        text: "This confirms payment and consumes the reserved stock.",
        confirmButtonText: "Complete order",
      }))
    )
      return;
    await api("/api/v1/commerce/staff/orders/" + o.id + "/complete/", {
      method: "POST",
      body: JSON.stringify({
        payment_method: o.payment_method || "CASH",
        idempotency_key: "fulfill:" + o.number,
      }),
    });
    load();
  };
  return (
    <>
      <span className="eyebrow">Sales history</span>
      <h1>Orders</h1>
      {!data.length ? (
        <Empty>No online orders.</Empty>
      ) : (
        <div className="list">
          {data.map((o) => (
            <article key={o.id}>
              <div>
                <b>{o.number}</b>
                <small>
                  {label(o.status)} · Payment: {label(o.payment_status).toLowerCase()}
                </small>
                {o.items.map((i) => (
                  <p key={i.id}>
                    {i.product_name} × {i.quantity}
                    {i.pick_locations?.map((a) => (
                      <em key={a.shelf_id}>
                        {" "}
                        · Pick {a.quantity} from {a.zone} →{" "}
                        {a.stack || "Unassigned stack"} → Level {a.level || "—"}{" "}
                        → {a.shelf_code}
                      </em>
                    ))}
                  </p>
                ))}
              </div>
              <strong>{businessCurrency()} {o.total}</strong>
              {!["PAID", "COMPLETED"].includes(o.status) && (
                <button onClick={() => void complete(o)}>
                  Confirm payment & consume reservation
                </button>
              )}
            </article>
          ))}
        </div>
      )}
    </>
  );
}
export function AnalyticsPage() {
  return (
    <>
      <span className="eyebrow">Reporting</span>
      <h1>Analytics</h1>
      <DashboardPage />
      <AdjustmentReport />
    </>
  );
}
