import { useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { FormError } from "../../components/forms/FormNotice";
import { addMpesaReference } from "./api";
import { CorrectTransaction } from "./CorrectTransaction";
import { useAuth } from "../../core/auth/AuthContext";

// 254712345678 → 0712 345 678, the way customers say their number.
export const localPhone = (phone) => (phone && phone.startsWith("254") ? `0${phone.slice(3, 6)} ${phone.slice(6, 9)} ${phone.slice(9)}` : phone || "—");

const time = (entry) => new Date(entry.occurred_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function AddCode({ entry, onSaved }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  if (!open) return <button type="button" className="secondary" onClick={() => setOpen(true)}>Add transaction ID</button>;
  return (
    <form className="inlineForm" onSubmit={async (event) => {
      event.preventDefault();
      setError("");
      try {
        await addMpesaReference(entry.id, code);
        await onSaved();
      } catch (err) {
        setError(err.message);
      }
    }}>
      <input aria-label={`Transaction ID for the ${Number(entry.amount).toLocaleString()} at ${time(entry)}`} required value={code} onChange={(event) => setCode(event.target.value)} />
      <button>Save</button>
      <FormError title="Could not save the transaction ID." message={error} />
    </form>
  );
}

// One kind of transaction from one shift (the caller passes only that shift's), newest first: deposits with the number and ID taken to process them,
// and each one's M-Pesa transaction ID once it is added. A closed shift's list (closed) can no longer be corrected.
export function CustomerTransactionList({ title, type, transactions, onChanged, scope = "this shift", closed = false }) {
  const { user } = useAuth();
  const canCorrect = !closed && Boolean(user?.permissions?.includes("mpesa.reverse_mpesa_transaction"));
  const reversed = new Set(transactions.filter((t) => t.reversal_of).map((t) => t.reversal_of));
  const rows = transactions.filter((t) => t.transaction_type === type);
  const deposit = type === "CUSTOMER_DEPOSIT";
  const total = rows.filter((t) => !reversed.has(t.id)).reduce((sum, t) => sum + Number(t.amount), 0);
  return (
    <section aria-labelledby={`${type}-heading${closed ? "-past" : ""}`}>
      <h2 id={`${type}-heading${closed ? "-past" : ""}`}>{title} {scope} ({rows.length})</h2>
      {!rows.length ? <p className="muted">None recorded {scope}.</p> : <>
        <p className="muted">Total {businessCurrency()} {total.toLocaleString()}{reversed.size ? ", not counting reversed ones" : ""}.</p>
        {/* Same grid table as "Agency transactions", so the three read alike. */}
        <div className={`table ledgerTable customerLedger ${deposit ? "depositLedger" : "withdrawalLedger"}`} role="table"
          aria-label={`${title} ${scope}`}>
          <div role="row">
            <b role="columnheader">Time</b>
            {deposit && <><b role="columnheader">M-Pesa number</b><b role="columnheader">ID number</b></>}
            <b role="columnheader">Amount</b>
            <b role="columnheader">Transaction ID</b>
            {canCorrect && <b role="columnheader"><span className="visuallyHidden">Correct</span></b>}
          </div>
          {rows.map((entry) => (
            <div key={entry.id} role="row" className={reversed.has(entry.id) ? "muted" : undefined}>
              <span role="rowheader">{time(entry)}{reversed.has(entry.id) && <small> · reversed</small>}{entry.corrects && <small> · corrected</small>}</span>
              {deposit && <><span role="cell">{localPhone(entry.customer_phone)}</span><span role="cell">{entry.customer_id_number || "—"}</span></>}
              <span role="cell">{businessCurrency()} {Number(entry.amount).toLocaleString()}</span>
              <span role="cell">{entry.provider_reference || (reversed.has(entry.id) ? "—" : <AddCode entry={entry} onSaved={onChanged} />)}</span>
              {canCorrect && <span role="cell">{!reversed.has(entry.id) && <CorrectTransaction entry={entry} onDone={onChanged} />}</span>}
            </div>
          ))}
        </div>
      </>}
    </section>
  );
}
