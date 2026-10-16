import { businessCurrency } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";

const amount = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const signed = (value) => `${value > 0 ? "+" : "−"}${amount(Math.abs(value))}`;
const cents = (value) => Math.round(value * 100) / 100;
const lastMonth = () => { const d = new Date(); d.setDate(0); return d.toLocaleDateString("en-CA").slice(0, 7); };

export const emptyOpening = () => ({ commission: false, month: lastMonth(), commissionAmount: "", reason: "" });

// The differences between what the last shift closed with and what is counted now: what is left after commission.
export function openingGaps(last, cash, electronicFloat, opening) {
  if (!last || last.cash == null) return { cash: 0, float: 0, extraFloat: 0 };
  const extraFloat = cents(Number(electronicFloat || 0) - Number(last.float));
  const earned = opening.commission ? Number(opening.commissionAmount || 0) : 0;
  return { cash: cents(Number(cash || 0) - Number(last.cash)), float: cents(extraFloat - earned), extraFloat: cents(extraFloat) };
}

// Opening a shift: the cash and float should be what the last shift closed with. More float can be Safaricom's
// commission paid in between (recorded as commission); any other difference needs a reason.
export function OpeningCheck({ last, cash, electronicFloat, opening, onChange, canRecordCommission }) {
  if (!last || last.cash == null) return null;
  const gaps = openingGaps(last, cash, electronicFloat, opening);
  const set = (change) => onChange({ ...opening, ...change });
  const counted = electronicFloat !== "";
  return (
    <div className="openingCheck" aria-label="Compared with the last shift">
      {last.agencyCash !== undefined
        ? <p className="muted">Expected now: cash <strong>{amount(last.cash)}</strong> and <strong>{amount(last.float)}</strong> on the line: what the
          last shift closed with (the agency's), plus the business's own money from sales since. Today's counts should match.</p>
        : <p className="muted">The last shift closed with cash <strong>{amount(last.cash)}</strong> and float <strong>{amount(last.float)}</strong>
          {last.updated_on ? ` (${new Date(`${last.updated_on}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" })})` : ""}.
          Today's counts should match.</p>}
      {counted && canRecordCommission && gaps.extraFloat > 0 && (
        <label className="checkRow">
          <input type="checkbox" checked={opening.commission}
            onChange={(event) => set({ commission: event.target.checked, commissionAmount: opening.commissionAmount || String(gaps.extraFloat) })} />
          The float is {amount(gaps.extraFloat)} more: Safaricom paid commission into it since the last shift closed
        </label>
      )}
      {counted && opening.commission && gaps.extraFloat > 0 && (
        <div className="loanFields">
          <FormField label="Month it was earned" type="month" required value={opening.month} onChange={(event) => set({ month: event.target.value })} />
          <FormField label={`Commission in the float (${businessCurrency()})`} type="number" min="0.01" step="0.01" max={gaps.extraFloat} required
            value={opening.commissionAmount} onChange={(event) => set({ commissionAmount: event.target.value })} />
        </div>
      )}
      {counted && (gaps.cash !== 0 || gaps.float !== 0) && (
        <>
          <p className="negative" role="status">Not matching the last shift: {gaps.cash !== 0 && <>cash {signed(gaps.cash)}</>}
            {gaps.cash !== 0 && gaps.float !== 0 && ", "}{gaps.float !== 0 && <>float {signed(gaps.float)}</>}
            {opening.commission && " after the commission"}.</p>
          <FormField label="Why it differs" required maxLength={500} value={opening.reason} placeholder="e.g. owner took 10,000 cash to the bank overnight"
            onChange={(event) => set({ reason: event.target.value })} />
        </>
      )}
    </div>
  );
}
