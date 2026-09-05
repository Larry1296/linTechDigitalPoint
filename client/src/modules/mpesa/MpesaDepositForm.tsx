import { useState } from "react";
import { postMpesaTransaction } from "./api";

export function MpesaDepositForm({ sessionId, onPosted }: { sessionId: number; onPosted: () => Promise<void> }) {
  const [message, setMessage] = useState("");
  const submit = async (event: React.FormEvent<HTMLFormElement>) => { event.preventDefault(); const form = new FormData(event.currentTarget); const entry = await postMpesaTransaction({ session: sessionId, transaction_type: "CUSTOMER_DEPOSIT", amount: form.get("amount"), provider_reference: form.get("reference"), customer_reference: form.get("customer_reference"), notes: form.get("notes"), idempotency_key: crypto.randomUUID() }); setMessage(`Recorded ${entry.internal_reference}`); event.currentTarget.reset(); await onPosted(); };
  return <form className="saleCart operatorForm" onSubmit={(event) => void submit(event)}><h2>Customer deposit</h2>{message && <p className="success">{message}</p>}<label>Amount (KES)<input name="amount" type="number" inputMode="decimal" min="1" step="0.01" required autoFocus /></label><label>M-Pesa agency reference<input name="reference" required /></label><label>Masked customer reference (optional)<input name="customer_reference" placeholder="e.g. 07***123" /></label><label>Notes<textarea name="notes" /></label><button>Record deposit</button></form>;
}
