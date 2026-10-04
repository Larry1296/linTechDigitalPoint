import { LogoImage } from "../../components/LogoImage";

// The customer's receipt, always in the selling business's own name and logo.
const money = (currency, value) =>
  `${currency === "KES" ? "KSh" : currency} ${Number(value).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const quantity = (value) => Number(value).toLocaleString("en-KE", { maximumFractionDigits: 3 });

export function receiptWhen(value) {
  return new Date(value).toLocaleString("en-KE", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export function ReceiptDocument({ receipt }) {
  const { business, branch, currency } = receipt;
  const contact = [branch?.address || business.address, branch?.phone || business.phone, business.email].filter(Boolean);
  return <article className="receiptDocument" aria-label={`Receipt ${receipt.number}`}>
    <header className="receiptHeader">
      {business.logo ? <LogoImage className="receiptLogo" slot="receipt" src={business.logo} alt={business.name} /> : null}
      <h2>{business.name}</h2>
      {branch && branch.name && <p>{branch.name}</p>}
      {contact.map((line) => <p key={line}>{line}</p>)}
    </header>
    <dl className="receiptMeta">
      <div><dt>Receipt</dt><dd>{receipt.number}</dd></div>
      <div><dt>Date</dt><dd>{receiptWhen(receipt.date)}</dd></div>
      <div><dt>Customer</dt><dd>{receipt.customer}</dd></div>
      {receipt.cashier && <div><dt>Served by</dt><dd>{receipt.cashier}</dd></div>}
    </dl>
    <ul className="receiptItems">
      {receipt.items.map((item, index) => <li key={index}>
        <div><strong>{item.name}</strong>{item.variant && <span> — {item.variant}</span>}
          <small>{quantity(item.quantity)} × {money(currency, item.unit_price)}{Number(item.discount) > 0 ? ` · less ${money(currency, item.discount)}` : ""}</small></div>
        <span>{money(currency, item.total)}</span>
      </li>)}
    </ul>
    <dl className="receiptTotals">
      {Number(receipt.discount) > 0 && <><div><dt>Subtotal</dt><dd>{money(currency, receipt.subtotal)}</dd></div>
        <div><dt>Discount</dt><dd>− {money(currency, receipt.discount)}</dd></div></>}
      <div className="receiptGrandTotal"><dt>Total</dt><dd>{money(currency, receipt.total)}</dd></div>
      {receipt.status === "COMPLETED" && receipt.charged !== undefined && Number(receipt.charged) !== Number(receipt.total) && <>
        <div><dt>Returns and price corrections</dt><dd>{Number(receipt.charged) < Number(receipt.total) ? "− " : "+ "}{money(currency, Math.abs(Number(receipt.total) - Number(receipt.charged)))}</dd></div>
        <div className="receiptGrandTotal"><dt>Now charged</dt><dd>{money(currency, receipt.charged)}</dd></div></>}
      {receipt.payments.map((payment, index) => <div key={index}><dt>{payment.method}{payment.status !== "COMPLETED" ? " (awaiting confirmation)" : ""}{payment.reference ? ` · ${payment.reference}` : ""}</dt><dd>{money(currency, payment.amount)}</dd></div>)}
      {Number(receipt.refunded) > 0 && <div><dt>Refunded</dt><dd>− {money(currency, receipt.refunded)}</dd></div>}
      {Number(receipt.balance) > 0 && <div className="receiptBalance"><dt>Balance due</dt><dd>{money(currency, receipt.balance)}</dd></div>}
    </dl>
    {receipt.status === "REFUNDED" && <p className="receiptStatus">Refunded — the goods were returned and payment given back.</p>}
    <footer className="receiptFooter">
      <p>{receipt.footer || "Thank you for your business."}</p>
    </footer>
  </article>;
}
