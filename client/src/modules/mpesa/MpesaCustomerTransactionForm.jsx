import { useState } from "react";
import { FormField } from "../../components/forms/FormField";
import { confirmAction } from "../../core/ui/alerts";
import { postMpesaTransaction } from "./api";

const transactionTypes = {
  CUSTOMER_DEPOSIT: { name: "deposit", effect: "add", direction: "to" },
  CUSTOMER_WITHDRAWAL: {
    name: "withdrawal",
    effect: "deduct",
    direction: "from",
  },
};

export function MpesaCustomerTransactionForm({
  transactionType,
  sessionId,
  availableCash,
  onPosted,
}) {
  const [message, setMessage] = useState("");
  const transaction = transactionTypes[transactionType];
  const isDeposit = transactionType === "CUSTOMER_DEPOSIT";
  const submit = async (event) => {
    event.preventDefault();
    // Capture the DOM form before awaiting confirmation; currentTarget is transient.
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    if (
      !(await confirmAction({
        title: `Record this customer ${transaction.name}?`,
        text: `This will ${transaction.effect} KSh ${form.get("amount")} ${transaction.direction} the agency ledger.`,
        confirmButtonText: `Record ${transaction.name}`,
      }))
    )
      return;
    const entry = await postMpesaTransaction({
      session: sessionId,
      transaction_type: transactionType,
      amount: form.get("amount"),
      provider_reference: form.get("reference"),
      customer_reference: form.get("customer_reference"),
      ...(isDeposit ? { notes: form.get("notes") } : {}),
      idempotency_key: crypto.randomUUID(),
    });
    setMessage(`Recorded ${entry.internal_reference}`);
    formElement.reset();
    await onPosted();
  };
  return (
    <form
      className="saleCart operatorForm"
      onSubmit={(event) => void submit(event)}
    >
      <h2>Customer {transaction.name}</h2>
      {!isDeposit && (
        <small>Available physical cash: KSh {availableCash}</small>
      )}
      {message && <p className="success">{message}</p>}
      <FormField
        label="Amount (KES)"
        name="amount"
        type="number"
        inputMode="decimal"
        min="1"
        max={isDeposit ? undefined : availableCash}
        step="0.01"
        required
        autoFocus={isDeposit}
      />
      <FormField label="M-Pesa agency reference" name="reference" required />
      <FormField
        label="Masked customer reference (optional)"
        name="customer_reference"
        placeholder="e.g. 07***123"
      />
      {isDeposit && (
        <FormField label="Notes">
          <textarea name="notes" />
        </FormField>
      )}
      <button>Record {transaction.name}</button>
    </form>
  );
}
