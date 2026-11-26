import { businessCurrency } from "../../core/organization/presentation";
import { useState } from "react";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { lookupMpesaCustomer, postMpesaTransaction } from "./api";
import { localPhone } from "./CustomerTransactionList";
import { CommissionBalanceField } from "./commissionBalance";

const transactionTypes = { CUSTOMER_DEPOSIT: { name: "deposit" }, CUSTOMER_WITHDRAWAL: { name: "withdrawal" } };

// What this transaction leaves you with, as a table: now, the change, and after. A deposit takes the amount
// from your float and adds it to your physical cash; a withdrawal pays out physical cash and adds it to float.
function BalancePreview({ deposit, cash, float, amount }) {
  if (cash == null || float == null) return null;
  const value = Number(amount) || 0;
  const rows = [
    ["Physical cash", Number(cash), deposit ? value : -value],
    ["Float", Number(float), deposit ? -value : value],
  ];
  const signed = (change) => (!change ? "—" : `${change > 0 ? "+" : "−"} ${Math.abs(change).toLocaleString()}`);
  const short = rows[deposit ? 1 : 0][1] + rows[deposit ? 1 : 0][2] < 0;
  return (
    <div className="balancePreview" aria-live="polite">
      <table>
        <caption>Balances ({businessCurrency()})</caption>
        <thead><tr><th scope="col"><span className="visuallyHidden">Balance</span></th><th scope="col">Now</th><th scope="col">This {deposit ? "deposit" : "withdrawal"}</th><th scope="col">After</th></tr></thead>
        <tbody>{rows.map(([label, now, change]) => (
          <tr key={label}>
            <th scope="row">{label}</th>
            <td>{now.toLocaleString()}</td>
            <td className={change < 0 ? "balanceDown" : change > 0 ? "balanceUp" : undefined}>{signed(change)}</td>
            <td aria-label={`${label === "Float" ? "Float" : "Cash"} after`}><strong>{(now + change).toLocaleString()}</strong></td>
          </tr>
        ))}</tbody>
      </table>
      {short && <p className="balanceShort" role="alert">{deposit ? "Not enough float for this deposit." : "Not enough physical cash for this withdrawal."}</p>}
    </div>
  );
}

const digits = (phone) => String(phone || "").replace(/\D/g, "");
const fullNumber = (phone) => { const d = digits(phone); return (d.length === 10 && d.startsWith("0")) || (d.length === 12 && d.startsWith("254")); };

// Quick to use while a customer waits: no confirmation pop-up (a mistake is fixed with Correct). A deposit records
// who it was for, the customer's M-Pesa number and the ID they showed, and a returning depositor's ID fills itself in
// from their number. The M-Pesa transaction code is not asked for: the number and ID are what the agent keeps.
export function MpesaCustomerTransactionForm({
  transactionType,
  sessionId,
  availableCash,
  availableFloat,
  employee = false,
  onPosted,
}) {
  const transaction = transactionTypes[transactionType];
  const isDeposit = transactionType === "CUSTOMER_DEPOSIT";
  const blank = { phone: "", idNumber: "", amount: "", commission: "" };
  const [fields, setFields] = useState(blank);
  const [known, setKnown] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key, value) => setFields((old) => ({ ...old, [key]: value }));
  const lookUp = async (phone) => {
    setKnown(null);
    if (!isDeposit || !fullNumber(phone)) return;
    try {
      const found = await lookupMpesaCustomer(phone);
      if (found?.found) {
        setKnown(found);
        setFields((old) => (old.idNumber ? old : { ...old, idNumber: found.id_number }));
      }
    } catch { /* the operator can still type the ID */ }
  };
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const entry = await postMpesaTransaction({
        session: sessionId,
        transaction_type: transactionType,
        amount: fields.amount,
        // A deposit carries the customer's number and ID; a withdrawal only its amount.
        ...(isDeposit ? { customer_phone: fields.phone, customer_id_number: fields.idNumber.trim() } : {}),
        ...(fields.commission.trim() ? { commission_balance: fields.commission.trim() } : {}),
        idempotency_key: crypto.randomUUID(),
      });
      const value = `${businessCurrency()} ${Number(entry.amount).toLocaleString()}`;
      setMessage(`Recorded ${transaction.name} of ${value}${isDeposit && entry.customer_phone ? ` to ${localPhone(entry.customer_phone)}` : ""}.`);
      setFields(blank);
      setKnown(null);
      await onPosted();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="saleCart operatorForm"
      onSubmit={(event) => void submit(event)}
    >
      <h2>Customer {transaction.name}</h2>
      {message && <p className="success">{message}</p>}
      {isDeposit && <>
        <FormField label="M-Pesa phone number" name="customer_phone" type="tel" inputMode="tel"
          placeholder="e.g. 0712 345 678" autoComplete="off" autoFocus value={fields.phone}
          onChange={(event) => { set("phone", event.target.value); void lookUp(event.target.value); }} />
        <FormField label="ID or passport number" name="customer_id_number" minLength={4} maxLength={20} autoComplete="off"
          value={fields.idNumber} onChange={(event) => set("idNumber", event.target.value)} />
        {known && <p className="muted returningCustomer">Returning customer: ID filled in from their last deposit ({known.visits} before).</p>}
      </>}
      <FormField
        label={`Amount (${businessCurrency()})`}
        name="amount"
        type="number"
        inputMode="decimal"
        min="1"
        max={isDeposit ? availableFloat : availableCash}
        step="0.01"
        required
        value={fields.amount}
        onChange={(event) => set("amount", event.target.value)}
      />
      {!employee && <CommissionBalanceField sessionId={sessionId} type={transactionType} amount={fields.amount} value={fields.commission} onChange={(value) => set("commission", value)} />}
      <BalancePreview deposit={isDeposit} cash={availableCash} float={availableFloat} amount={fields.amount} />
      <button disabled={busy}>Record {transaction.name}</button>
      <FormError title={`Could not record the ${transaction.name}.`} message={error} />
    </form>
  );
}
