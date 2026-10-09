import { useEffect, useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";
import { getCommissionAdvice } from "./api";

// Safaricom's commission balance on the agent line, read right after the transaction is done. The box shows only
// while the app has not learned the commission on this amount; once it has, the box goes away and the commission is
// worked out by itself. It never blocks a waiting customer: it is optional, and shown if the app cannot be reached.
export function CommissionBalanceField({ sessionId, type, amount, value, onChange }) {
  const [advice, setAdvice] = useState(null);
  useEffect(() => {
    setAdvice(null);
    if (!sessionId || !(Number(amount) > 0)) return undefined;
    let live = true;
    const timer = setTimeout(() => {
      getCommissionAdvice(sessionId, type, amount)
        .then((found) => { if (live) setAdvice(found); })
        .catch(() => { if (live) setAdvice({ ask: true }); });
    }, 300);
    return () => { live = false; clearTimeout(timer); };
  }, [sessionId, type, amount]);
  if (!advice) return null;
  if (!advice.ask) {
    return <p className="muted commissionKnown" role="status">Commission: <b>{businessCurrency()} {Number(advice.earned).toLocaleString()}</b>, worked out automatically.</p>;
  }
  return (
    <>
      <p className="muted" role="status">The app is still learning the commission on this amount: enter the commission balance after this transaction.</p>
      <FormField label={`Commission balance after (${businessCurrency()}, optional)`} name="commission_balance" type="number" inputMode="decimal"
        min="0" step="0.01" placeholder="As shown on the agent line after this transaction" autoComplete="off"
        value={value} onChange={(event) => onChange(event.target.value)} />
    </>
  );
}

// What one transaction earned: measured from its reading, learned by the app ("≈"), or not known yet ("—").
export function earnedLabel(entry) {
  if (entry.commission_earned == null) return "—";
  const earned = Number(entry.commission_earned).toLocaleString();
  return entry.commission_source === "learned" ? `≈ ${earned}` : earned;
}
