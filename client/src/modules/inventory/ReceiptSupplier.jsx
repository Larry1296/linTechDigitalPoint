import { useRef, useState } from "react";
import { api } from "../../core/api/client";
import { businessCurrency, businessTimeZone } from "../../core/organization/presentation";
import { askForm, confirmAction } from "../../core/ui/alerts";
import { FormError } from "../../components/forms/FormNotice";
import { usePayableInvestments } from "../receiving/ReceiptCosts";
import { TextArea } from "../../components/forms/TextBox";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const day = (value) => new Date(value).toLocaleDateString("en-CA", { timeZone: businessTimeZone() });
const shown = (value) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
const SOURCES = [["CASH", "Shop cash drawer"], ["MPESA", "M-Pesa (Lipa na M-Pesa till)"], ["BANK", "Bank"],
  ["OWNER", "My own money (not from the shop)"]];

// What this receipt says is owed to its supplier, and the two right ways to clear it: record the payment, or say
// the stock was already yours. The stock itself is never returned or entered again.
export function ReceiptSupplier({ receipt, can, onSaved }) {
  const supplier = receipt.supplier;
  const [mode, setMode] = useState("");
  const [error, setError] = useState("");
  if (!supplier) return null;
  const owed = Number(supplier.owed);
  const save = (data, message) => { setMode(""); setError(""); onSaved(data, message); };
  async function undoPayment(payment) {
    const answer = await askForm({ title: `Undo the ${money(payment.amount)} payment?`, confirmButtonText: "Undo payment",
      text: `The money goes back to ${payment.source_label.toLowerCase()} and ${supplier.supplier} is owed it again.`,
      fields: [{ name: "reason", label: "Why", required: true, value: "Recorded by mistake" }] });
    const reason = answer?.reason;
    if (!reason) return;
    try {
      save(await api(`/api/v1/inventory/receipts/${receipt.id}/payments/${payment.id}/undo/`, { method: "POST", body: JSON.stringify({ reason }) }),
        `Payment undone. ${supplier.supplier} is owed ${money(Number(supplier.owed) + Number(payment.amount))} again.`);
    } catch (e) { setError(e.message); }
  }
  async function undoAlreadyOwned() {
    const answer = await askForm({ title: "Turn this back into a purchase?", confirmButtonText: "Make it a purchase",
      text: `${supplier.supplier} will be owed ${money(supplier.amount)} for it again.`,
      fields: [{ name: "reason", label: "Why", required: true, value: `Bought from ${supplier.supplier}` }] });
    const reason = answer?.reason;
    if (!reason) return;
    try {
      save(await api(`/api/v1/inventory/receipts/${receipt.id}/already-owned/undo/`, { method: "POST", body: JSON.stringify({ reason }) }),
        `This receipt is a purchase again: ${supplier.supplier} is owed ${money(supplier.amount)}.`);
    } catch (e) { setError(e.message); }
  }
  return (
    <section className="panel" aria-label="Supplier balance">
      <h3>Supplier: {supplier.supplier}</h3>
      {supplier.already_owned ? (
        <>
          <p>Stock you already owned, entered as opening stock. Nothing is owed to {supplier.supplier} for it.</p>
          {can.markOwned && <button type="button" className="secondary" onClick={undoAlreadyOwned}>It was a purchase after all</button>}
        </>
      ) : (
        <>
          <p>
            Bought {money(supplier.amount)}
            {Number(supplier.returned) > 0 && <> · returned {money(supplier.returned)}</>}
            {" "}· paid {money(supplier.paid)} · <strong>{owed > 0 ? `still owed ${money(owed)}` : "nothing owed"}</strong>
          </p>
          {owed > 0 && !mode && (
            <p>
              {can.pay && <button type="button" onClick={() => setMode("pay")}>I paid {supplier.supplier}</button>}{" "}
              {can.markOwned && supplier.can_mark_already_owned && (
                <button type="button" className="secondary" onClick={() => setMode("owned")}>This stock was already mine</button>
              )}
            </p>
          )}
          {mode === "pay" && <PayForm receipt={receipt} onCancel={() => setMode("")} onSaved={save} />}
          {mode === "owned" && <AlreadyOwnedForm receipt={receipt} onCancel={() => setMode("")} onSaved={save} />}
        </>
      )}
      {supplier.payments.length > 0 && (
        <ul aria-label="Payments to the supplier">
          {supplier.payments.map((p) => (
            <li key={p.id}>
              {shown(p.paid_on)} · {money(p.amount)} from {p.source_label}
              {p.undone ? " · undone" : can.undo && <> <button type="button" className="secondary" onClick={() => undoPayment(p)}>Undo</button></>}
            </li>
          ))}
        </ul>
      )}
      <FormError title="Could not save." message={error} />
    </section>
  );
}

function PayForm({ receipt, onCancel, onSaved }) {
  const supplier = receipt.supplier;
  const received = day(receipt.received_at);
  const today = day(new Date());
  const [amount, setAmount] = useState(String(Number(supplier.owed)));
  const [paidOn, setPaidOn] = useState(today);
  const [source, setSource] = useState("CASH");
  const [investmentId, setInvestmentId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  const { investments } = usePayableInvestments();
  const investment = investments.find((i) => String(i.id) === String(investmentId)) || (investments.length === 1 ? investments[0] : null);
  const from = source === "INVESTMENT" ? `${investment?.name || "your investment"} (your own money)`
    : SOURCES.find(([value]) => value === source)[1].toLowerCase();
  const valid = Number(amount) > 0 && Number(amount) <= Number(supplier.owed) && paidOn && paidOn >= received && paidOn <= today
    && (source !== "INVESTMENT" || investment);
  async function submit(event) {
    event.preventDefault();
    if (!valid || busy) return;
    if (!(await confirmAction({ title: `Record ${money(amount)} paid to ${supplier.supplier}?`,
      text: `Paid on ${shown(paidOn)} from ${from}. ${source === "OWNER" || source === "INVESTMENT" ? "Your shop drawer, till and bank stay as they are; it counts as your own money paying the supplier." : "It comes off that money on that day."} What is owed for ${receipt.receipt_number} goes down to ${money(Number(supplier.owed) - Number(amount))}.`,
      confirmButtonText: "Record payment" }))) return;
    setBusy(true); setError("");
    try {
      const data = await api(`/api/v1/inventory/receipts/${receipt.id}/pay-supplier/`, { method: "POST", body: JSON.stringify({
        amount, source, paid_on: paidOn, idempotency_key: key.current,
        ...(source === "INVESTMENT" ? { investment_id: investment.id } : {}) }) });
      onSaved(data, `Payment recorded. ${Number(data.supplier.owed) > 0 ? `Still owed: ${money(data.supplier.owed)}.` : `Nothing is owed to ${supplier.supplier} for this receipt now.`}`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} aria-label="Record payment to supplier">
      <fieldset disabled={busy}>
        <legend>Record a payment to {supplier.supplier}</legend>
        <label>Amount paid ({businessCurrency()})
          <input type="number" min="0.01" step="0.01" max={supplier.owed} required value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>Date paid
          <input type="date" min={received} max={today} required value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </label>
        <small>If you paid when the stock arrived, choose {shown(received)}.</small>
        <label>Where the money came from
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            {SOURCES.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
            {investments.length > 0 && <option value="INVESTMENT">My investment (MMF)</option>}
          </select>
        </label>
        {source === "INVESTMENT" && <>
          {investments.length > 1 && <label>Taken out of
            <select value={investmentId} required onChange={(e) => setInvestmentId(e.target.value)}>
              <option value="" disabled>Choose the investment</option>
              {investments.map((i) => <option key={i.id} value={i.id}>{i.name} · holds {money(i.value)}</option>)}
            </select>
          </label>}
          <small>Taken out of the investment to you and paid straight to the supplier as your own money; the business's till and bank are not touched.</small>
        </>}
        <button disabled={!valid || busy}>Review payment</button>{" "}
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </fieldset>
      <FormError title="Could not record the payment." message={error} />
    </form>
  );
}

function AlreadyOwnedForm({ receipt, onCancel, onSaved }) {
  const supplier = receipt.supplier;
  const [reason, setReason] = useState("I had this stock before I started recording in the app");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    if (!reason.trim() || busy) return;
    if (!(await confirmAction({ title: "Mark this stock as already yours?",
      text: `${receipt.receipt_number} becomes opening stock worth ${money(supplier.amount)}. Nothing will be owed to ${supplier.supplier}, it will not count as stock bought, and the items, shelves and buying prices stay exactly as they are.`,
      confirmButtonText: "Mark as already mine" }))) return;
    setBusy(true); setError("");
    try {
      const data = await api(`/api/v1/inventory/receipts/${receipt.id}/already-owned/`, { method: "POST", body: JSON.stringify({ reason: reason.trim() }) });
      onSaved(data, `Done. ${receipt.receipt_number} is now opening stock and nothing is owed to ${supplier.supplier}.`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} aria-label="Stock already owned">
      <fieldset disabled={busy}>
        <legend>This stock was already mine</legend>
        <p>Use this when the items were yours before you started recording, and you entered them through Receive stock instead of as opening stock. Nothing was bought, so nothing is owed.</p>
        <label>Why
          <TextArea required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button disabled={!reason.trim() || busy}>Review</button>{" "}
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </fieldset>
      <FormError title="Could not change the receipt." message={error} />
    </form>
  );
}
