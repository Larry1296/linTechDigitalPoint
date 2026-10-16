import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { label } from "../../core/ui/labels";

export const NEW_RECEIPT_COSTS = { document_status: "SUPPLIER_DOCUMENT", landed_costs: [], payment_method: "", payment_amount: "",
  investment_id: "", investment_name: "", payment_via: "MPESA" };
const VIA = [["MPESA", "M-Pesa"], ["BANK", "Bank"]];
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const PAID_BY = [["SUPPLIER_INVOICE", "On the supplier's invoice"], ["CASH", "Paid now in cash"], ["MPESA", "Paid now by M-Pesa"], ["BANK", "Paid now by bank"]];

// The receipt's supplier document, delivery (landed) costs and whether the supplier was paid on delivery.
export function receiptCostsProblem(details) {
  if (!details.supplier_name?.trim() && details.document_status !== "OPENING_BALANCE") return "Enter the supplier.";
  if (details.document_status === "SUPPLIER_DOCUMENT" && !details.external_reference?.trim())
    return "Enter the supplier's invoice or delivery note number, or tick 'No supplier document'.";
  for (const [index, cost] of (details.landed_costs || []).entries())
    if (!cost.description?.trim() || Number(cost.amount) <= 0) return `Delivery cost ${index + 1}: describe it and enter an amount above zero.`;
  if (details.payment_method && Number(details.payment_amount) <= 0) return "Enter how much was paid to the supplier now.";
  if (details.payment_method === "INVESTMENT" && !details.investment_id) return "Choose the investment the money comes out of.";
  return "";
}

export function receiptCostsPayload(details) {
  const { payment_method, payment_amount, investment_id, payment_via, ...rest } = details;
  delete rest.investment_name;  // shown in the review only
  if (!payment_method || Number(payment_amount) <= 0) return rest;
  const fromInvestment = payment_method === "INVESTMENT" ? { investment_id: Number(investment_id), via: payment_via } : {};
  return { ...rest, payment: { method: payment_method, amount: payment_amount, ...fromInvestment } };
}

export function paymentSummary(details) {
  if (!details.payment_method) return "Owed to the supplier";
  if (details.payment_method === "INVESTMENT")
    return `${details.payment_amount} paid now from ${details.investment_name || "your investment"} (taken out to ${details.payment_via === "BANK" ? "bank" : "M-Pesa"})`;
  if (details.payment_method === "OWNER") return `${details.payment_amount} paid now from your own pocket (money you put into the business)`;
  return `${details.payment_amount} paid now (${label(details.payment_method)})`;
}

// Investments (e.g. an MMF) the supplier can be paid from, for people allowed to take money out of them.
export function usePayableInvestments() {
  const { user } = useAuth();
  const allowed = Boolean(user?.organization?.enabled_modules?.includes("investments"))
    && ["accounting.view_investment", "accounting.add_investmentmovement"].every((p) => user?.permissions?.includes(p));
  const [investments, setInvestments] = useState([]);
  const [locked, setLocked] = useState(false);
  useEffect(() => {
    if (!allowed) return undefined;
    let live = true;
    api("/api/v1/accounting/investments/")
      .then((data) => { if (live) setInvestments(data.investments.filter((i) => Number(i.value) > 0)); })
      // Without them the supplier is simply paid from cash, M-Pesa or bank; investments stay hidden until the
      // protected pages password is entered.
      .catch((err) => { if (live && err.data?.code === "protected_locked") setLocked(true); });
    return () => { live = false; };
  }, [allowed]);
  return { investments, locked };
}

export function ReceiptDocumentFields({ details, onChange }) {
  const set = (changes) => onChange({ ...details, ...changes });
  const noDocument = details.document_status === "NO_DOCUMENT";
  return <>
    <label>Supplier invoice / delivery note number
      <input value={details.external_reference} disabled={noDocument} required={!noDocument}
        onChange={(e) => set({ external_reference: e.target.value })} placeholder={noDocument ? "A reference will be created" : "e.g. INV-2041"} />
    </label>
    <label className="checkRow">
      <input type="checkbox" checked={noDocument} onChange={(e) => set({ document_status: e.target.checked ? "NO_DOCUMENT" : "SUPPLIER_DOCUMENT", external_reference: e.target.checked ? "" : details.external_reference })} />
      No supplier document (e.g. bought at the market)
    </label>
  </>;
}

export function ReceiptCostFields({ details, onChange, goodsTotal }) {
  const set = (changes) => onChange({ ...details, ...changes });
  const { investments, locked: investmentsLocked } = usePayableInvestments();
  const investment = investments.find((i) => String(i.id) === String(details.investment_id));
  const chooseInvestment = (id) => set({ investment_id: id, investment_name: investments.find((i) => String(i.id) === String(id))?.name || "" });
  const costs = details.landed_costs || [];
  const setCost = (index, changes) => set({ landed_costs: costs.map((cost, i) => (i === index ? { ...cost, ...changes } : cost)) });
  const landed = costs.reduce((sum, cost) => sum + Number(cost.amount || 0), 0);
  return <fieldset className="receiptCosts">
    <legend>Delivery and other costs</legend>
    <p className="muted">Transport, loading or handling paid to get this stock here. They are added to the stock's cost, shared across the items by value.</p>
    {costs.map((cost, index) => <div className="receiptCostRow" key={index}>
      <label>What for<input value={cost.description} onChange={(e) => setCost(index, { description: e.target.value })} placeholder="e.g. Boda boda from supplier" /></label>
      <label>Amount<input type="number" min="0.01" step="0.01" value={cost.amount} onChange={(e) => setCost(index, { amount: e.target.value })} /></label>
      <label>How paid<select value={cost.paid_by} onChange={(e) => setCost(index, { paid_by: e.target.value })}>
        {PAID_BY.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <button type="button" className="secondary" onClick={() => set({ landed_costs: costs.filter((_, i) => i !== index) })}>Remove</button>
    </div>)}
    <button type="button" className="secondary" onClick={() => set({ landed_costs: [...costs, { description: "", amount: "", paid_by: "CASH" }] })}>Add a delivery cost</button>
    <label>Paid the supplier now?
      <select value={details.payment_method} onChange={(e) => {
        const method = e.target.value;
        const only = method === "INVESTMENT" && !details.investment_id && investments.length === 1 ? investments[0] : null;
        set({ payment_method: method, payment_amount: method && !details.payment_amount ? String(goodsTotal || "") : details.payment_amount,
          ...(only ? { investment_id: String(only.id), investment_name: only.name } : {}) });
      }}>
        <option value="">No — owe the supplier (pay later)</option>
        <option value="CASH">Yes, in cash</option>
        <option value="MPESA">Yes, by M-Pesa</option>
        <option value="BANK">Yes, by bank</option>
        <option value="OWNER">Yes, from my own pocket (not the business's money)</option>
        {investments.length > 0 && <option value="INVESTMENT">Yes, from my investment (MMF)</option>}
      </select>
    </label>
    {investmentsLocked && <small>To pay from an investment, open <a href="/admin/investments" target="_blank" rel="noreferrer">Investments</a> with
      your protected pages password first, then come back.</small>}
    {details.payment_method === "INVESTMENT" && <div className="receiptInvestment">
      {investments.length > 1 && <label>Take it out of
        <select value={details.investment_id} required onChange={(e) => chooseInvestment(e.target.value)}>
          <option value="" disabled>Choose the investment</option>
          {investments.map((i) => <option key={i.id} value={i.id}>{i.name} · holds {money(i.value)}</option>)}
        </select>
      </label>}
      <label>Withdrawn to
        <select value={details.payment_via} onChange={(e) => set({ payment_via: e.target.value })}>
          {VIA.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select>
      </label>
      {investment && <p className={Number(details.payment_amount) > Number(investment.value) ? "formWarning" : "muted"}>
        {investment.name} holds {money(investment.value)}.{" "}
        {Number(details.payment_amount) > Number(investment.value)
          ? "That is less than the amount paid: record interest from its statement first, or pay part from elsewhere."
          : `It is recorded as taken out to ${details.payment_via === "BANK" ? "the bank" : "M-Pesa"} and paid straight to the supplier, so your till and bank stay as they are.`}
      </p>}
    </div>}
    {details.payment_method && <label>Amount paid now ({businessCurrency()})
      <input type="number" min="0.01" step="0.01" value={details.payment_amount} onChange={(e) => set({ payment_amount: e.target.value })} />
    </label>}
    {landed > 0 && <p className="muted">Goods {businessCurrency()} {Number(goodsTotal || 0).toFixed(2)} + delivery {businessCurrency()} {landed.toFixed(2)} = stock cost {businessCurrency()} {(Number(goodsTotal || 0) + landed).toFixed(2)}</p>}
  </fieldset>;
}
