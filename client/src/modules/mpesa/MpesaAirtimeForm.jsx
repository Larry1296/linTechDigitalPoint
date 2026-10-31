import { useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { postMpesaTransaction } from "./api";
import { localPhone } from "./CustomerTransactionList";
import { AIRTIME_PAID_BY, paidByLabel } from "./airtime";
import { CommissionBalanceField } from "./commissionBalance";

// Airtime (credit) for a customer. It is not a deposit or a withdrawal and not income: only the commission
// Safaricom pays on it is, recorded on the Commission page.
export function MpesaAirtimeForm({ sessionId, availableCash, availableFloat, onPosted, employee = false }) {
  const blank = { phone: "", amount: "", code: "", paidBy: "CASH", commission: "" };
  const [fields, setFields] = useState(blank);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key, value) => setFields((old) => ({ ...old, [key]: value }));
  const option = AIRTIME_PAID_BY.find((item) => item.id === fields.paidBy);
  const value = Number(fields.amount) || 0;
  const [cashChange, floatChange] = option.effect(value);
  const short = availableFloat != null && value > Number(availableFloat);
  const signed = (change) => (!change ? "—" : `${change > 0 ? "+" : "−"} ${Math.abs(change).toLocaleString()}`);
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const entry = await postMpesaTransaction({
        session: sessionId, transaction_type: "AIRTIME_SALE", amount: fields.amount, paid_by: fields.paidBy,
        customer_phone: fields.phone, ...(fields.code.trim() ? { provider_reference: fields.code.trim() } : {}),
        ...(fields.commission.trim() ? { commission_balance: fields.commission.trim() } : {}),
        idempotency_key: crypto.randomUUID(),
      });
      setMessage(`Recorded airtime of ${businessCurrency()} ${Number(entry.amount).toLocaleString()}${entry.customer_phone ? ` to ${localPhone(entry.customer_phone)}` : ""}, paid by ${paidByLabel(entry.paid_by).toLowerCase()}.`);
      setFields(blank);
      await onPosted();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="saleCart operatorForm" onSubmit={(event) => void submit(event)}>
      <h2>Airtime (credit)</h2>
      <p className="muted">Airtime you send to a customer from the float. It is not a deposit, and the money is not your income; only Safaricom's commission on it is, recorded with the rest of your monthly commission.</p>
      {message && <p className="success">{message}</p>}
      <FormField label="Number the airtime was sent to (optional)" name="customer_phone" type="tel" inputMode="tel" placeholder="e.g. 0712 345 678"
        autoComplete="off" value={fields.phone} onChange={(event) => set("phone", event.target.value)} />
      <FormField label={`Amount (${businessCurrency()})`} name="amount" type="number" inputMode="decimal" min="1" max={availableFloat} step="0.01" required
        value={fields.amount} onChange={(event) => set("amount", event.target.value)} />
      <fieldset className="airtimePaidBy">
        <legend>The customer paid by</legend>
        {AIRTIME_PAID_BY.map((item) => <label key={item.id}>
          <input type="radio" name="paid_by" value={item.id} checked={fields.paidBy === item.id} onChange={() => set("paidBy", item.id)} />
          <span><b>{item.label}</b> <small className="muted">{item.hint}</small></span>
        </label>)}
      </fieldset>
      <FormField label={fields.paidBy === "CASH" ? "Transaction ID (optional)" : "Customer's M-Pesa code (optional)"} name="provider_reference" autoComplete="off"
        value={fields.code} onChange={(event) => set("code", event.target.value.toUpperCase())} />
      {!employee && <CommissionBalanceField sessionId={sessionId} type="AIRTIME_SALE" amount={fields.amount} value={fields.commission} onChange={(value) => set("commission", value)} />}
      {availableCash != null && availableFloat != null && <div className="balancePreview" aria-live="polite">
        <table>
          <caption>Balances ({businessCurrency()})</caption>
          <thead><tr><th scope="col"><span className="visuallyHidden">Balance</span></th><th scope="col">Now</th><th scope="col">This airtime</th><th scope="col">After</th></tr></thead>
          <tbody>{[["Physical cash", Number(availableCash), cashChange], ["Float", Number(availableFloat), floatChange]].map(([label, now, change]) => (
            <tr key={label}>
              <th scope="row">{label}</th><td>{now.toLocaleString()}</td>
              <td className={change < 0 ? "balanceDown" : change > 0 ? "balanceUp" : undefined}>{signed(change)}</td>
              <td aria-label={`${label === "Float" ? "Float" : "Cash"} after`}><strong>{(now + change).toLocaleString()}</strong></td>
            </tr>
          ))}</tbody>
        </table>
        {short && <p className="balanceShort" role="alert">Not enough float to send this airtime.</p>}
      </div>}
      <button disabled={busy}>Record airtime</button>
      <FormError title="Could not record the airtime." message={error} />
    </form>
  );
}
