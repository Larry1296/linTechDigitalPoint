import { businessCurrency } from "../../core/organization/presentation";
import { useState } from "react";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { lookupMpesaCustomer, postMpesaTransaction } from "./api";
import { readMpesaMessage } from "./mpesaMessage";
import { localPhone } from "./CustomerTransactionList";

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

// Quick to use while a customer waits: no confirmation pop-up (a mistake is fixed with Correct), a returning
// depositor's ID fills itself in from their phone number, and a pasted M-Pesa message fills in the code, amount
// and number, so a transaction can also be recorded after the customer has left.
export function MpesaCustomerTransactionForm({
  transactionType,
  sessionId,
  availableCash,
  availableFloat,
  onPosted,
}) {
  const transaction = transactionTypes[transactionType];
  const isDeposit = transactionType === "CUSTOMER_DEPOSIT";
  const blank = { phone: "", idNumber: "", amount: "", code: "" };
  const [fields, setFields] = useState(blank);
  const [known, setKnown] = useState(null);
  const [pasted, setPasted] = useState(null);
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
  const readMessage = (text) => {
    const read = readMpesaMessage(text);
    setPasted({ ...read, empty: !read.code && !read.amount && !read.phone });
    setFields((old) => ({ ...old, code: read.code || old.code, amount: read.amount || old.amount, phone: (isDeposit && read.phone) || old.phone }));
    if (isDeposit && read.phone) void lookUp(read.phone);
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
        // A deposit may carry the customer's number and ID (both optional); a withdrawal only its amount.
        ...(isDeposit ? { customer_phone: fields.phone, customer_id_number: fields.idNumber } : {}),
        ...(fields.code.trim() ? { provider_reference: fields.code.trim() } : {}),
        idempotency_key: crypto.randomUUID(),
      });
      const value = `${businessCurrency()} ${Number(entry.amount).toLocaleString()}`;
      setMessage(`Recorded ${transaction.name} of ${value}${isDeposit && entry.customer_phone ? ` to ${localPhone(entry.customer_phone)}` : ""}${entry.provider_reference ? ` (${entry.provider_reference})` : ". Add its transaction ID below once it's done"}.`);
      setFields(blank);
      setKnown(null);
      setPasted(null);
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
      <details className="pasteMessage">
        <summary>Paste the M-Pesa message</summary>
        <label>M-Pesa confirmation message
          <textarea rows={3} placeholder="Paste the message here: the transaction ID, amount and number are filled in for you"
            onChange={(event) => readMessage(event.target.value)} />
        </label>
        {pasted && <p className={pasted.empty ? "formNotice formNoticeError" : "muted"} role="status">{pasted.empty
          ? "Nothing recognisable in that message. Fill in the details below."
          : `Found: ${[pasted.code && `transaction ID ${pasted.code}`, pasted.amount && `amount ${Number(pasted.amount).toLocaleString()}`, isDeposit && pasted.phone && `number ${pasted.phone}`].filter(Boolean).join(", ")}. Check them below.`}</p>}
      </details>
      {isDeposit && <>
        <FormField label="M-Pesa phone number (optional)" name="customer_phone" type="tel" inputMode="tel"
          placeholder="e.g. 0712 345 678" autoComplete="off" autoFocus value={fields.phone}
          onChange={(event) => { set("phone", event.target.value); void lookUp(event.target.value); }} />
        <FormField label="ID or passport number (optional)" name="customer_id_number" minLength={4} maxLength={20} autoComplete="off"
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
      <FormField label="Transaction ID (optional)" name="provider_reference" autoComplete="off" placeholder="If already done"
        value={fields.code} onChange={(event) => set("code", event.target.value.toUpperCase())} />
      <BalancePreview deposit={isDeposit} cash={availableCash} float={availableFloat} amount={fields.amount} />
      <button disabled={busy}>Record {transaction.name}</button>
      <FormError title={`Could not record the ${transaction.name}.`} message={error} />
    </form>
  );
}
