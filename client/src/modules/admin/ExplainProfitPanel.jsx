import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { ErrorState, Loading } from "../../components/States";
import { useMoney } from "./AccountingReportsPage";

// Traces one sale line's profit to its prices, the stock deliveries it came from and every journal.
export function ExplainProfitPanel({ itemId, onClose }) {
  const [data, setData] = useState();
  const [error, setError] = useState("");
  useEffect(() => { api(`/api/v1/accounting/explain/sale-items/${itemId}/`).then(setData).catch((e) => setError(e.message)); }, [itemId]);
  useEffect(() => {
    const close = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  const money = useMoney();
  const line = data?.line;
  return <div className="shelfOverlay" role="presentation" onMouseDown={onClose}>
    <div className="shelfPanel" role="dialog" aria-modal="true" aria-label="How this profit was worked out" onMouseDown={(e) => e.stopPropagation()}>
      <header className="shelfPanelHeader">
        <div><span className="eyebrow">{data ? `${data.sale.number} · ${data.sale.date?.slice(0, 10)}` : "Sale line"}</span><h2>{line?.item || "Loading…"}</h2></div>
        <button type="button" className="shelfClose" onClick={onClose} aria-label="Close">×</button>
      </header>
      {error ? <ErrorState message={error} /> : !data ? <Loading /> : <>
        <section className="shelfStats" aria-label="Result">
          <div><span>Net revenue</span><strong>{money(line.net_revenue)}</strong></div>
          <div><span>Cost of goods</span><strong>{line.cost_pending ? "Not final" : money(line.cogs)}</strong></div>
          <div><span>{line.loss ? "Loss" : "Gross profit"}</span><strong className={line.loss ? "lossText" : undefined}>{money(line.gross_profit)}{line.loss ? " LOSS" : ""}</strong></div>
        </section>
        {line.cost_pending && <p className="formNotice formNoticeInfo">Some of these units came from stock without a recorded buying price, so the cost and profit are not final.</p>}
        <dl className="explainFacts">
          <div><dt>Customer · payment</dt><dd>{data.sale.customer} · {data.sale.payment_status.replace("_", " ").toLowerCase()}</dd></div>
          <div><dt>Branch · cashier</dt><dd>{data.sale.branch || "—"} · {data.sale.cashier || "—"}</dd></div>
          <div><dt>Quantity</dt><dd>{Number(line.quantity)}{Number(line.returned_quantity) ? ` (${Number(line.returned_quantity)} returned)` : ""}</dd></div>
          <div><dt>Catalogue price</dt><dd>{line.catalogue_price != null ? money(line.catalogue_price) : "—"}</dd></div>
          <div><dt>Actual price each</dt><dd>{money(line.actual_price)}</dd></div>
          <div><dt>Line amount</dt><dd>{money(line.gross)}</dd></div>
          <div><dt>Discount</dt><dd>{money(line.discount)}{line.discount_reason ? ` · ${line.discount_reason}` : ""}</dd></div>
          <div><dt>Tax (not your revenue)</dt><dd>{money(line.tax)}</dd></div>
        </dl>
        <p className="muted">{line.formula}</p>
        <h3>Where the cost came from</h3>
        {!data.cost_layers.length ? <p className="muted">A service with no stock used. Its cost is the configured direct cost.</p> : <table className="reportTable">
          <thead><tr><th>Delivery</th><th>Qty</th><th>Cost each</th><th>Cost</th></tr></thead>
          <tbody>{data.cost_layers.map((layer, i) => <tr key={i}>
            <td data-label="Delivery">{layer.delivery} · {layer.supplier || "no supplier"}<br /><small className="muted">received {layer.received_at?.slice(0, 10)} · buying price {money(layer.buying_price)}{Number(layer.landed_cost_per_unit) ? ` + delivery ${money(layer.landed_cost_per_unit)}` : ""}{layer.uncosted ? " · buying price missing" : ""}</small></td>
            <td data-label="Qty">{Number(layer.quantity)}</td><td data-label="Cost each">{money(layer.unit_cost)}</td><td data-label="Cost">{money(layer.cost)}</td>
          </tr>)}</tbody>
        </table>}
        {data.returns.length > 0 && <><h3>Returns</h3><ul>{data.returns.map((r) => <li key={r.number}>{r.number}: {Number(r.quantity)} unit(s) {r.restocked ? "back on the shelf" : "written off"} · sales −{money(r.net)} · {r.reason}</li>)}</ul></>}
        {data.notes.length > 0 && <><h3>Price corrections</h3><ul>{data.notes.map((n, i) => <li key={i}>{n.kind === "CREDIT" ? "Price lowered by" : "Price raised by"} {money(n.amount)} · {n.reason}</li>)}</ul></>}
        <h3>How it was recorded (for your accountant)</h3>
        {data.journals.map((j) => <details key={j.id}><summary>{j.date} · {j.description}</summary>
          <table className="reportTable"><thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead><tbody>
            {j.lines.map((l, i) => <tr key={i}><th scope="row">{l.account} · {l.name}</th><td data-label="Debit">{Number(l.debit) ? money(l.debit) : ""}</td><td data-label="Credit">{Number(l.credit) ? money(l.credit) : ""}</td></tr>)}
          </tbody></table></details>)}
      </>}
    </div>
  </div>;
}
