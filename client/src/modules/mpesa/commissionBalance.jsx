import { businessCurrency } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";

// Safaricom's commission balance on the agent line, read right after the transaction is done. The rise from the
// last reading is what this transaction earned. Optional, so a waiting customer is never held up.
export function CommissionBalanceField({ value, onChange }) {
  return (
    <FormField label={`Commission balance after (${businessCurrency()}, optional)`} name="commission_balance" type="number" inputMode="decimal"
      min="0" step="0.01" placeholder="As shown on the agent line after this transaction" autoComplete="off"
      value={value} onChange={(event) => onChange(event.target.value)} />
  );
}
