import { useState } from "react";
import { businessCurrency, businessTimeZone } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { CashCounter, countPayload, countTotal, emptyCount } from "./CashCounter";
import { businessDate } from "./businessDay";

const amount = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const signed = (value) => `${Number(value) > 0 ? "+" : ""}${Number(value).toLocaleString()}`;
export const when = (value) => new Date(value).toLocaleString([], { timeZone: businessTimeZone(), weekday: "short", day: "numeric",
  month: "short", hour: "2-digit", minute: "2-digit" });
const longDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });

// Where the week's shift stands: running, its last day today, or past its Saturday and waiting to be closed.
// Shifts opened before weekly shifts (no runs_until) ran a day, so they are past due once their day is over.
export function weekState(session, today = businessDate()) {
  if (!session) return null;
  const last = session.runs_until || businessDate(session.opened_at);
  return { last, label: longDay(last), state: today > last ? "over" : today === last ? "last-day" : "running" };
}

// A count of the cash and float in the middle of the week, compared with what the records say. The total, cash plus
// float, is what must agree; deposits and withdrawals only swap one for the other. An employee counts blind.
export function MoneyCheckForm({ dashboard, surprise, onCount, onCancel }) {
  const employee = Boolean(dashboard.employee);
  const [count, setCount] = useState(emptyCount);
  const [float, setFloat] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cash = countTotal(count);
  const total = cash + (Number(float) || 0);
  const expected = Number(dashboard.cash) + Number(dashboard.float);
  const difference = Math.round((total - expected) * 100) / 100;
  const differs = !employee && float !== "" && difference !== 0;
  const splitOff = !employee && float !== "" && difference === 0 && Math.abs(cash - Number(dashboard.cash)) >= 0.005;
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onCount({ actual_cash: cash.toFixed(2), actual_float: float, cash_count: countPayload(count), reason, check: surprise?.id });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard shiftForm" onSubmit={(event) => void submit(event)} aria-label="Money check">
      <h2>{surprise ? "Surprise money check" : "Check the money now"}</h2>
      <p className="muted">Count the agency's cash and read its float off the M-Pesa line. Carry on serving customers once it is recorded; the shift stays open.</p>
      <fieldset disabled={busy}>
        <CashCounter count={count} onChange={setCount} legend="Count the agency's own cash" />
        <FormField label="The agency's float on the M-Pesa line" name="actual_float" type="number" min="0" step="0.01" required
          value={float} onChange={(event) => setFloat(event.target.value)} />
        {employee ? <p className="muted">Count carefully: the business owner checks your count against the records.</p> : <dl className="reportPosition">
          <div><dt>Money in operation: counted vs records</dt><dd><strong>{amount(total)}</strong> vs {amount(expected)}{float !== "" && difference !== 0 && ` (${signed(difference)})`}</dd></div>
          <div><dt>Cash: counted vs records</dt><dd>{amount(cash)} vs {amount(dashboard.cash)}</dd></div>
          <div><dt>Float: entered vs records</dt><dd>{amount(float)} vs {amount(dashboard.float)}</dd></div>
        </dl>}
        {splitOff && <p className="formNotice" role="status">The total agrees, but the cash and float are split differently from the records: a deposit or withdrawal may not be recorded, or recorded the wrong way round.</p>}
        {differs && <FormField label="Why is the total different? (required)" name="reason" required value={reason}
          onChange={(event) => setReason(event.target.value)} />}
        <div className="actionRow">
          <button>Record the count</button>
          {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
        </div>
      </fieldset>
      <FormError title="Could not record the money check." message={error} />
    </form>
  );
}

// The owner's list of the week's checks so far: when, who counted, and whether the total agreed.
export function MoneyChecks({ session }) {
  const checks = session?.money_checks || [];
  const left = session?.money_checks_left || 0;
  return (
    <section aria-labelledby="money-checks-heading">
      <h2 id="money-checks-heading">Money checks this week</h2>
      <p className="muted">
        {left ? `${left} surprise ${left === 1 ? "check is" : "checks are"} still to come this week, on days and at times nobody is shown.`
          : "No more surprise checks this week."} You can check the money yourself at any time.
      </p>
      {checks.length > 0 && <ul className="moneyChecks">
        {checks.map((check) => (
          <li key={check.id} className={Number(check.difference) ? "due" : undefined}>
            <b>{when(check.counted_at)}</b> · {check.surprise ? "surprise check" : "your check"} by {check.counted_by}:
            {" "}{amount(check.total)} counted vs {amount(check.expected_total)} in the records
            {Number(check.difference) ? <> · <strong>{signed(check.difference)}</strong>{check.reason && ` (${check.reason})`}</>
              : Number(check.split_off) ? " · total agrees, but the cash and float split differs" : " · agrees"}
          </li>
        ))}
      </ul>}
    </section>
  );
}
