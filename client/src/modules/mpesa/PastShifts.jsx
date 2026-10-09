import { useState } from "react";
import { businessCurrency, businessTimeZone } from "../../core/organization/presentation";
import { FormError } from "../../components/forms/FormNotice";
import { getMpesaShiftTransactions, getPastMpesaShifts } from "./api";
import { CustomerTransactionList } from "./CustomerTransactionList";
import { businessDate } from "./businessDay";
import { ShiftChart } from "./ShiftChart";

const day = (value) => new Date(value).toLocaleDateString([], { timeZone: businessTimeZone(), weekday: "short", day: "numeric", month: "short", year: "numeric" });
const clock = (value) => new Date(value).toLocaleTimeString([], { timeZone: businessTimeZone(), hour: "2-digit", minute: "2-digit" });
const figure = (value) => Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = (value) => `${Number(value) > 0 ? "+" : ""}${figure(value)}`;

// When a shift ran: "Sat, 3 Oct 2026, 08:02 – 18:30", with the closing day too when it closed on another day.
export const shiftPeriod = (shift) => `${day(shift.opened_at)}, ${clock(shift.opened_at)} – ${
  businessDate(shift.closed_at) === businessDate(shift.opened_at) ? "" : `${day(shift.closed_at)}, `}${clock(shift.closed_at)}`;

const CUSTOMER = ["CUSTOMER_DEPOSIT", "CUSTOMER_WITHDRAWAL", "AIRTIME_SALE"];

// Closing a shift clears the desk, but its records are kept. Here they can be opened again: the list holds only
// closed shifts that have records, each named by when it ran, and picking one shows just that shift's records.
export function PastShifts() {
  const [shifts, setShifts] = useState();
  const [picked, setPicked] = useState("");
  const [records, setRecords] = useState();
  const [error, setError] = useState("");
  const showList = async () => {
    setError("");
    try {
      setShifts(await getPastMpesaShifts());
    } catch (err) {
      setError(err.message);
    }
  };
  const pick = async (id) => {
    setPicked(id);
    setRecords(undefined);
    setError("");
    if (!id) return;
    try {
      setRecords(await getMpesaShiftTransactions(id));
    } catch (err) {
      setError(err.message);
    }
  };
  const close = () => {
    setShifts(undefined);
    setPicked("");
    setRecords(undefined);
  };
  const shift = shifts?.find((row) => String(row.id) === picked);
  const reload = () => pick(picked);
  const others = (records || []).filter((entry) => !CUSTOMER.includes(entry.transaction_type));
  return (
    <section className="monthlyReport pastShifts" aria-labelledby="past-shifts-heading">
      <div className="sectionHeading">
        <h2 id="past-shifts-heading">Past shifts</h2>
        {shifts
          ? <button type="button" className="secondary" onClick={close}>Hide past shifts</button>
          : <button type="button" className="secondary" onClick={() => void showList()}>Look at a past shift</button>}
      </div>
      {!shifts && <p className="muted">Closed shifts leave the desk but their records are kept. Open one here to see its deposits and withdrawals again.</p>}
      {shifts && !shifts.length && <p className="muted">No closed shift has records yet.</p>}
      {shifts?.length > 0 && (
        <label>Shift
          <select value={picked} onChange={(event) => void pick(event.target.value)}>
            <option value="">Choose when the shift ran</option>
            {shifts.map((row) => (
              <option key={row.id} value={row.id}>
                {shiftPeriod(row)} · {row.outlet} · {row.operator} ({row.records} {row.records === 1 ? "record" : "records"})
              </option>
            ))}
          </select>
        </label>
      )}
      {shift && (
        <p className="muted pastShiftSummary">
          Opened with cash {businessCurrency()} {figure(shift.opening_cash)} and float {businessCurrency()} {figure(shift.opening_float)}.
          Closed with cash {businessCurrency()} {figure(shift.closing_cash)} and float {businessCurrency()} {figure(shift.closing_float)}
          {Number(shift.cash_variance) || Number(shift.float_variance)
            ? ` (cash ${signed(shift.cash_variance)}, float ${signed(shift.float_variance)} against what was expected).`
            : ", as expected."}
          {shift.month_forecast && ` When it closed, ${shift.month_forecast.label}'s commission was heading for ${businessCurrency()} ${figure(shift.month_forecast.forecast)} (${businessCurrency()} ${figure(shift.month_forecast.so_far)} so far, ${shift.month_forecast.days_left} ${shift.month_forecast.days_left === 1 ? "day" : "days"} left).`}
        </p>
      )}
      {shift && !records && !error && <p className="muted" role="status">Loading the shift's records…</p>}
      {shift && records && (
        <div className="pastShiftRecords">
          <ShiftChart transactions={records} openedAt={shift.opened_at} closedAt={shift.closed_at} />
          <CustomerTransactionList title="Deposits" type="CUSTOMER_DEPOSIT" transactions={records} onChanged={reload} scope="in that shift" closed />
          <CustomerTransactionList title="Withdrawals" type="CUSTOMER_WITHDRAWAL" transactions={records} onChanged={reload} scope="in that shift" closed />
          <CustomerTransactionList title="Airtime sold" type="AIRTIME_SALE" transactions={records} onChanged={reload} scope="in that shift" closed />
          {others.length > 0 && (
            <section aria-labelledby="past-other-heading">
              <h2 id="past-other-heading">Other movements in that shift ({others.length})</h2>
              <div className="table ledgerTable agencyLedger" role="table" aria-label="Other movements in that shift">
                <div role="row"><b role="columnheader">Time</b><b role="columnheader">Type</b><b role="columnheader">Amount</b>
                  <b role="columnheader">Cash effect</b><b role="columnheader">Float effect</b><b role="columnheader">Reference</b></div>
                {others.map((entry) => (
                  <div key={entry.id} role="row">
                    <span role="rowheader">{clock(entry.occurred_at)}</span>
                    <span role="cell">{entry.transaction_type.replaceAll("_", " ").toLowerCase()}</span>
                    <span role="cell">{businessCurrency()} {figure(entry.amount)}</span>
                    <span role="cell">{signed(entry.cash_delta)}</span>
                    <span role="cell">{signed(entry.float_delta)}</span>
                    <span role="cell">{entry.provider_reference || entry.internal_reference}</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
      <FormError title="Could not open the past shifts." message={error} />
    </section>
  );
}
