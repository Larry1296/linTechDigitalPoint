import { useEffect, useState } from "react";
import { businessCurrency } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";
import { getCommissionAdvice } from "./api";

// Safaricom's commission balance on the agent line, read right after the transaction is done. The app asks for it
// only when it has not learned the commission on this amount yet, or now and then as a check on Safaricom's rates;
// otherwise it shows the commission it already knows. It never blocks a waiting customer.
export function CommissionBalanceField({ sessionId, type, amount, value, onChange }) {
  const [advice, setAdvice] = useState(null);
  const [anyway, setAnyway] = useState(false);
  useEffect(() => {
    setAdvice(null);
    setAnyway(false);
    if (!sessionId || !(Number(amount) > 0)) return undefined;
    let live = true;
    const timer = setTimeout(() => {
      getCommissionAdvice(sessionId, type, amount).then((found) => { if (live) setAdvice(found); }).catch(() => {});
    }, 300);
    return () => { live = false; clearTimeout(timer); };
  }, [sessionId, type, amount]);
  if (advice && !advice.ask && !anyway && !value) {
    return (
      <p className="muted commissionKnown" role="status">
        Commission on this: <b>{businessCurrency()} {Number(advice.earned).toLocaleString()}</b>, learned from your earlier readings. No need to read the balance.{" "}
        <button type="button" className="linkButton" onClick={() => setAnyway(true)}>Enter it anyway</button>
      </p>
    );
  }
  return (
    <>
      {advice?.reason === "new" && <p className="muted" role="status">The app has not learned the commission on this amount yet: enter the commission balance after this transaction.</p>}
      {advice?.reason === "check" && <p className="muted" role="status">A quick check: enter the commission balance, so the app knows Safaricom's rates have not changed.</p>}
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
