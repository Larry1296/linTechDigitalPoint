import { useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { confirmAction } from "../../core/ui/alerts";
import { FormError } from "../../components/forms/FormNotice";
import { correctMpesaTransaction } from "./api";
import { AIRTIME_PAID_BY } from "./airtime";

const localPhone = (phone) => (phone && phone.startsWith("254") ? `0${phone.slice(3)}` : phone || "");
const LABELS = { CUSTOMER_DEPOSIT: "deposit", CUSTOMER_WITHDRAWAL: "withdrawal", AIRTIME_SALE: "airtime sale", FLOAT_TOPUP: "float top-up", CASH_REBALANCE: "cash rebalance" };

// Fix a wrong amount, number, ID or transaction ID. The wrong entry is reversed and the right one recorded,
// linked together with the reason, so nothing is lost and cash, float and the monthly report stay correct.
export function CorrectTransaction({ entry, onDone }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const deposit = entry.transaction_type === "CUSTOMER_DEPOSIT";
  const airtime = entry.transaction_type === "AIRTIME_SALE";
  if (!LABELS[entry.transaction_type]) return null;
  if (!open) return <button type="button" className="secondary" onClick={() => setOpen(true)}>Correct</button>;
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!(await confirmAction({ title: `Correct this ${LABELS[entry.transaction_type]}?`,
      text: `The ${businessCurrency()} ${Number(entry.amount).toLocaleString()} entry is reversed and ${businessCurrency()} ${Number(values.amount).toLocaleString()} is recorded in its place, with your reason.`,
      confirmButtonText: "Save correction" }))) return;
    setBusy(true);
    setError("");
    try {
      await correctMpesaTransaction(entry.id, values);
      setOpen(false);
      await onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="correctForm" onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy}>
        <label>Correct amount ({businessCurrency()})<input name="amount" type="number" min="1" step="0.01" required defaultValue={Number(entry.amount)} /></label>
        {deposit && <label>M-Pesa number (optional)<input name="customer_phone" type="tel" defaultValue={localPhone(entry.customer_phone)} /></label>}
        {deposit && <label>ID number (optional)<input name="customer_id_number" defaultValue={entry.customer_id_number} /></label>}
        {airtime && <label>Sent to (optional)<input name="customer_phone" type="tel" defaultValue={localPhone(entry.customer_phone)} /></label>}
        {airtime && <label>Paid by<select name="paid_by" defaultValue={entry.paid_by}>{AIRTIME_PAID_BY.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>}
        <label>Transaction ID<input name="provider_reference" defaultValue={entry.provider_reference || ""} placeholder="If known" /></label>
        <label className="correctReason">What was wrong?<input name="reason" required maxLength={240} placeholder="e.g. typed 700, customer deposited 500" /></label>
        <div className="actionRow"><button>Save correction</button><button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button></div>
      </fieldset>
      <FormError title="Could not correct it." message={error} />
    </form>
  );
}
