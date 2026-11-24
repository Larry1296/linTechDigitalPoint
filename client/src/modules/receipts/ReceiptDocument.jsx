import { createPortal } from "react-dom";
import { LogoImage } from "../../components/LogoImage";

// The customer's receipt, always in the selling business's own name and logo.
const money = (currency, value) =>
  `${currency === "KES" ? "KSh" : currency} ${Number(value).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const quantity = (value) => Number(value).toLocaleString("en-KE", { maximumFractionDigits: 3 });

export function receiptWhen(value) {
  return new Date(value).toLocaleString("en-KE", { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

// A business logo is served by the API. Older receipts may carry it under the web app's address (which has no logos),
// so the path alone is kept and the app's own API address is put in front of it.
const LOGO_PATH = /^https?:\/\/[^/]+(\/api\/v1\/tenancy\/public\/logos\/.+)$/;
export function receiptLogo(src) {
  const match = typeof src === "string" ? src.match(LOGO_PATH) : null;
  return match ? match[1] : src;
}

// Where the sale stands, in one plain word for the customer.
export function receiptState(receipt) {
  if (receipt.status === "REFUNDED") return { label: "Refunded", tone: "bad" };
  if (receipt.status === "CANCELLED") return { label: "Cancelled", tone: "bad" };
  if (Number(receipt.balance) > 0) return Number(receipt.paid) > 0 ? { label: "Part paid", tone: "due" } : { label: "Not paid", tone: "due" };
  return { label: "Paid in full", tone: "good" };
}

export function ReceiptDocument({ receipt }) {
  const { business, branch, currency } = receipt;
  const contact = [branch?.address || business.address, branch?.phone || business.phone, business.email].filter(Boolean);
  const pieces = receipt.items.reduce((sum, item) => sum + Number(item.quantity), 0);
  const lineDiscounts = receipt.items.reduce((sum, item) => sum + Number(item.discount || 0), 0);
  const gross = receipt.items.reduce((sum, item) => sum + Number(item.quantity) * Number(item.unit_price), 0);
  const state = receiptState(receipt);
  const paidTotal = receipt.payments.filter((p) => p.status === "COMPLETED").reduce((sum, p) => sum + Number(p.amount), 0);
  return <article className="receiptDocument" aria-label={`Receipt ${receipt.number}`}>
    <header className="receiptHeader">
      {business.logo ? <LogoImage className="receiptLogo" slot="receipt" src={receiptLogo(business.logo)} alt={business.name} /> : null}
      <h2>{business.name}</h2>
      {branch && branch.name && <p>{branch.name}</p>}
      {contact.map((line) => <p key={line}>{line}</p>)}
    </header>
    <p className="receiptTitle">Sales receipt</p>
    <dl className="receiptMeta">
      <div><dt>Receipt no.</dt><dd>{receipt.number}</dd></div>
      <div><dt>Date</dt><dd>{receiptWhen(receipt.date)}</dd></div>
      <div><dt>Customer</dt><dd>{receipt.customer}</dd></div>
      {receipt.cashier && <div><dt>Served by</dt><dd>{receipt.cashier}</dd></div>}
      {receipt.channel && <div><dt>Sold at</dt><dd>{receipt.channel}</dd></div>}
    </dl>
    <div className="receiptItemsHead" aria-hidden="true"><span>Item · qty × price</span><span>Amount</span></div>
    <ul className="receiptItems">
      {receipt.items.map((item, index) => <li key={index}>
        <div><strong>{item.name}</strong>{item.variant && item.variant !== item.name && <span className="receiptVariant">{item.variant}</span>}
          <small>{quantity(item.quantity)} × {money(currency, item.unit_price)}{Number(item.discount) > 0 ? ` · less ${money(currency, item.discount)}` : ""}</small></div>
        <span>{money(currency, item.total)}</span>
      </li>)}
    </ul>
    <p className="receiptCount">{receipt.items.length} {receipt.items.length === 1 ? "item" : "items"} · {quantity(pieces)} {pieces === 1 ? "piece" : "pieces"} in all</p>
    <dl className="receiptTotals">
      {(Number(receipt.discount) > 0 || lineDiscounts > 0) && <>
        <div><dt>Before discount</dt><dd>{money(currency, gross)}</dd></div>
        <div><dt>Discount</dt><dd>− {money(currency, lineDiscounts + Number(receipt.discount))}</dd></div></>}
      <div className="receiptGrandTotal"><dt>Total</dt><dd>{money(currency, receipt.total)}</dd></div>
      {receipt.status === "COMPLETED" && receipt.charged !== undefined && Number(receipt.charged) !== Number(receipt.total) && <>
        <div><dt>Returns and price corrections</dt><dd>{Number(receipt.charged) < Number(receipt.total) ? "− " : "+ "}{money(currency, Math.abs(Number(receipt.total) - Number(receipt.charged)))}</dd></div>
        <div className="receiptGrandTotal"><dt>Now charged</dt><dd>{money(currency, receipt.charged)}</dd></div></>}
    </dl>
    {receipt.payments.length > 0 && <dl className="receiptTotals receiptPayments">
      {receipt.payments.map((payment, index) => <div key={index}><dt>Paid by {payment.method}{payment.status !== "COMPLETED" ? " (awaiting confirmation)" : ""}{payment.reference ? <small>Ref. {payment.reference}</small> : null}</dt><dd>{money(currency, payment.amount)}</dd></div>)}
      {receipt.payments.length > 1 && <div><dt>Total paid</dt><dd>{money(currency, paidTotal)}</dd></div>}
      {Number(receipt.refunded) > 0 && <div><dt>Refunded</dt><dd>− {money(currency, receipt.refunded)}</dd></div>}
    </dl>}
    {Number(receipt.balance) > 0 && <dl className="receiptTotals"><div className="receiptBalance"><dt>Balance due</dt><dd>{money(currency, receipt.balance)}</dd></div></dl>}
    <p className={`receiptState receiptState-${state.tone}`}>{state.label}</p>
    {receipt.status === "REFUNDED" && <p className="receiptStatus">Refunded — the goods were returned and payment given back.</p>}
    <footer className="receiptFooter">
      <p>{receipt.footer || "Thank you for your business."}</p>
      <p className="receiptKeep">Please keep this receipt. Quote {receipt.number} for any return or question.</p>
    </footer>
  </article>;
}

// The paper copy: placed straight under <body>, so printing shows only the receipt on as many pages as it needs
// (one, for a normal sale) instead of the whole app behind it as blank pages.
export function ReceiptPrintCopy({ receipt }) {
  return createPortal(<div className="receiptPrintCopy" aria-hidden="true"><ReceiptDocument receipt={receipt} /></div>, document.body);
}

// The tab title is what a saved PDF is named and what the browser may print at the top of the page.
export function printReceipt(receipt) {
  const before = document.title;
  document.title = `Receipt ${receipt.number} · ${receipt.business.name}`;
  const restore = () => { document.title = before; window.removeEventListener("afterprint", restore); };
  window.addEventListener("afterprint", restore);
  window.print();
}
