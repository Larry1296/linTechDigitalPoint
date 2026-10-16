import { businessCurrency } from "../../core/organization/presentation";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import { MetricCard } from "../../components/dashboard/MetricCard";
import { useEffect, useRef, useState } from "react";
import { Empty, ErrorState, Loading } from "../../components/States";
import { useAuth } from "../../core/auth/AuthContext";
import {
  createMpesaOutlet,
  deleteMpesaOutlet,
  updateMpesaOutlet,
  getMpesaDashboard,
  getMpesaOutlets,
  getMpesaTransactions,
  openMpesaSession,
  postMpesaTransaction,
  reconcileMpesaSession,
  recordMpesaCommissionBalance,
  reverseMpesaTransaction,
} from "./api";
import { MpesaDepositForm } from "./MpesaDepositForm";
import { CustomerTransactionList } from "./CustomerTransactionList";
import { CorrectTransaction } from "./CorrectTransaction";
import { MonthlyReport } from "./MonthlyReport";
import { PastShifts } from "./PastShifts";
import { ShiftChart } from "./ShiftChart";
import { MpesaAnalysis } from "./MpesaAnalysis";
import { MpesaWithdrawalForm } from "./MpesaWithdrawalForm";
import { MpesaAirtimeForm } from "./MpesaAirtimeForm";
import { askForm, confirmAction, showError } from "../../core/ui/alerts";
import { businessDate, useNewBusinessDay } from "./businessDay";
import { CashCounter, countFrom, countPayload, countTotal, emptyCount } from "./CashCounter";
import { OpeningCheck, emptyOpening, openingGaps } from "./OpeningCheck";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { TOPUP_SOURCES } from "./topUp";

const figure = (value) => Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// Money in shows as +, money out as −, no change as —.
const signedFigure = (value) => (Number(value) > 0 ? `+${figure(value)}` : Number(value) < 0 ? `−${figure(-Number(value))}` : "—");
const amount = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const signedAmount = (value) => `${Number(value) < 0 ? "−" : "+"}${amount(Math.abs(Number(value)))}`;

// How the commission balance was reached since the last reading: commission the app worked out, less what was paid out.
function commissionSince(money) {
  const added = Number(money.commission_worked_out) > 0;
  const paid = Number(money.commission_paid_out) > 0;
  const unknown = Number(money.commission_unknown) || 0;
  if (money.commission_read == null || (!added && !paid && !unknown)) return "";
  const parts = [`Last read ${amount(money.commission_read)}`];
  if (added) parts.push(`+ ${amount(money.commission_worked_out)} worked out since`);
  if (paid) parts.push(`− ${amount(money.commission_paid_out)} paid out or used`);
  if (unknown) parts.push(`${unknown} transaction${unknown === 1 ? "" : "s"} not worked out yet`);
  return parts.join(" · ");
}

// The outlet's name and the numbers M-Pesa gave it; used both to add and to edit.
function OutletForm({ outlet, onSave, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await onSave({ display_name: values.get("display_name"), agent_reference: values.get("agent_reference"), store_number: values.get("store_number") });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard shiftForm" onSubmit={(event) => void submit(event)}>
      <h3>{outlet ? `Edit ${outlet.display_name}` : "Add an M-Pesa outlet"}</h3>
      {!outlet && <p>An outlet is the M-Pesa agent till you serve customers from.</p>}
      <fieldset disabled={busy}>
        <FormField label="Outlet name" name="display_name" required maxLength={160} defaultValue={outlet?.display_name} />
        <FormField label="Agent number" name="agent_reference" maxLength={80} defaultValue={outlet?.agent_reference} />
        <FormField label="Store number" name="store_number" maxLength={80} defaultValue={outlet?.store_number} />
        <div className="actionRow">
          <button>Save outlet</button>
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
        </div>
      </fieldset>
      <FormError title="Could not save the outlet." message={error} />
    </form>
  );
}

// Every outlet with its numbers and the money in operation last recorded. Each day except Sunday needs a
// fresh figure (a shift opened or closed that day); until then the figures show in red as due.
function OutletCards({ outlets, canChange, canDelete, canRead, onChanged }) {
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const run = async (action) => {
    setError("");
    try {
      await action();
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  };
  const toggle = (outlet) => run(async () => {
    if (!(await confirmAction({ title: `${outlet.active ? "Deactivate" : "Reactivate"} ${outlet.display_name}?`,
      text: outlet.active ? "No new shifts can be opened on it. Its history is kept." : "Shifts can be opened on it again.",
      confirmButtonText: outlet.active ? "Deactivate" : "Reactivate" }))) return;
    await updateMpesaOutlet(outlet.id, { active: !outlet.active });
  });
  const remove = (outlet) => run(async () => {
    if (!(await confirmAction({ title: `Delete ${outlet.display_name}?`, text: "Only an outlet that has never had a shift can be deleted.",
      confirmButtonText: "Delete outlet" }))) return;
    await deleteMpesaOutlet(outlet.id);
  });
  // A reading taken while the shift is open (say it opened before the app asked for one): the next transaction is measured from it.
  const readCommission = (outlet) => run(async () => {
    const current = outlet.money_in_operation.commission_balance;
    const values = await askForm({ title: `Commission balance on ${outlet.display_name}`,
      text: "Read the commission balance off the agent line now. The next transaction's commission is measured from it.",
      confirmButtonText: "Record balance",
      fields: [{ name: "balance", label: "Commission balance now", required: true, placeholder: "e.g. 1250.50", value: current == null ? "" : String(Number(current)) }] });
    if (!values) return;
    await recordMpesaCommissionBalance(outlet.money_in_operation.open_session, values.balance);
  });
  if (!outlets.length) return null;
  return (
    <>
      <FormError title="Could not change the outlet." message={error} />
      <ul className="outletCards">
        {outlets.map((outlet) => {
          const money = outlet.money_in_operation;
          if (editing === outlet.id) return <li key={outlet.id}>
            <OutletForm outlet={outlet} onCancel={() => setEditing(null)}
              onSave={async (body) => { await updateMpesaOutlet(outlet.id, body); setEditing(null); await onChanged(); }} />
          </li>;
          return (
            <li key={outlet.id} className={money.due && outlet.active ? "outletCard due" : "outletCard"}>
              <h3>{outlet.display_name}{!outlet.active && <small className="muted"> · inactive</small>}</h3>
              <dl>
                <div><dt>Agent number</dt><dd>{outlet.agent_reference || "—"}</dd></div>
                <div><dt>Store number</dt><dd>{outlet.store_number || "—"}</dd></div>
                <div><dt>Money in operation</dt><dd className="outletMoney">{money.total == null ? "Not recorded yet" : amount(money.total)}</dd></div>
                <div><dt>Cash</dt><dd className="outletMoney">{money.cash == null ? "—" : amount(money.cash)}</dd></div>
                <div><dt>Float</dt><dd className="outletMoney">{money.float == null ? "—" : amount(money.float)}</dd></div>
                <div><dt>Commission balance</dt><dd className="outletMoney">{money.commission_balance == null ? "Not recorded yet" : amount(money.commission_balance)}</dd></div>
              </dl>
              {commissionSince(money) && <p className="muted">{commissionSince(money)}</p>}
              {money.due && outlet.active
                ? <p className="outletDue" role="status">Update due: today's cash and float are not recorded yet{money.updated_on ? ` (last recorded ${money.updated_on})` : ""}. Open or close a shift to record them.</p>
                : money.updated_on && <p className="muted">Recorded {money.updated_on}</p>}
              {canRead && money.open_session && <div className="actionRow">
                <button type="button" className="secondary" onClick={() => void readCommission(outlet)}>Record commission balance</button>
              </div>}
              {(canChange || canDelete) && <div className="actionRow">
                {canChange && <button type="button" className="secondary" onClick={() => setEditing(outlet.id)}>Edit</button>}
                {canChange && <button type="button" className="secondary" onClick={() => void toggle(outlet)}>{outlet.active ? "Deactivate" : "Reactivate"}</button>}
                {canDelete && <button type="button" className="danger" onClick={() => void remove(outlet)}>Delete</button>}
              </div>}
            </li>
          );
        })}
      </ul>
    </>
  );
}

// Closing: count the drawer, enter the float from the M-Pesa line, and compare the full amount with the opening.
// One drawer for the whole business (server mpesa/combined.py): the shift counts all the cash in the drawer and all the
// money on the agent line. What to expect is the agency's part plus the business's own money from sales.
export function expectedCount(money) {
  const combined = money?.combined;
  if (!combined || money.cash == null) return money;
  return { ...money, agencyCash: money.cash, agencyFloat: money.float,
    cash: Number(money.cash) + Number(combined.business_cash), float: Number(money.float) + Number(combined.business_line) };
}

function CombinedExpected({ dashboard }) {
  const combined = dashboard.combined;
  return <div className="combinedExpected">
    <p className="muted">This shift counts all the money: the agency's and the business's own sales money, together in the drawer
      {combined.sale_mpesa_to === "AGENT_LINE" ? " and on the agent line" : ""}.</p>
    <table className="combinedTable">
      <caption>What to expect at closing</caption>
      <thead><tr><th scope="col">Expected</th><th scope="col">Drawer</th>{combined.sale_mpesa_to === "AGENT_LINE" && <th scope="col">Agent line</th>}</tr></thead>
      <tbody>
        <tr><th scope="row">The agency's (opening, deposits and withdrawals)</th><td>{amount(dashboard.cash)}</td>{combined.sale_mpesa_to === "AGENT_LINE" && <td>{amount(dashboard.float)}</td>}</tr>
        <tr><th scope="row">The business's at opening</th><td>{amount(combined.business_cash_at_open)}</td>{combined.sale_mpesa_to === "AGENT_LINE" && <td>{amount(combined.business_line_at_open)}</td>}</tr>
        {(combined.since_open || []).map((row) => <tr key={row.label}><th scope="row">{row.label}, since opening</th>
          <td>{Number(row.cash) ? signedAmount(row.cash) : "—"}</td>{combined.sale_mpesa_to === "AGENT_LINE" && <td>{Number(row.line) ? signedAmount(row.line) : "—"}</td>}</tr>)}
      </tbody>
      <tfoot><tr><th scope="row">Expected now</th><td>{amount(Number(dashboard.cash) + Number(combined.business_cash))}</td>
        {combined.sale_mpesa_to === "AGENT_LINE" ? <td>{amount(Number(dashboard.float) + Number(combined.business_line))}</td> : null}</tr></tfoot>
    </table>
    {combined.sale_mpesa_to !== "AGENT_LINE" && <p className="muted">M-Pesa paid for sales goes to the business's own till, so the agent line holds the agency's float only.</p>}
  </div>;
}

function CloseShift({ dashboard, onClose, onCancel }) {
  const [count, setCount] = useState(emptyCount);
  const [float, setFloat] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cash = countTotal(count);
  const combined = dashboard.combined;
  const expectedCash = Number(dashboard.cash) + Number(combined?.business_cash || 0);
  const expectedFloat = Number(dashboard.float) + Number(combined?.business_line || 0);
  const cashVariance = cash - expectedCash;
  const floatVariance = (Number(float) || 0) - expectedFloat;
  const total = cash + (Number(float) || 0) - Number(combined?.business_cash || 0) - Number(combined?.business_line || 0);
  const opening = Number(dashboard.in_operation.opening);
  const variance = Math.abs(cashVariance) >= 0.005 || (float !== "" && Math.abs(floatVariance) >= 0.005);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onClose({ actual_cash: cash.toFixed(2), actual_float: float, cash_count: countPayload(count), reason });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard shiftForm" onSubmit={(event) => void submit(event)}>
      <h2>Close & reconcile shift</h2>
      <fieldset disabled={busy}>
        {combined && <CombinedExpected dashboard={dashboard} />}
        <CashCounter count={count} onChange={setCount} legend={combined ? "Count all the cash in the drawer" : "Count the cash in the drawer"} />
        <FormField label={combined?.sale_mpesa_to === "AGENT_LINE" ? "All the money on the agent line" : "Float on the M-Pesa line"} name="actual_float" type="number" min="0" step="0.01" required
          value={float} onChange={(event) => setFloat(event.target.value)} />
        <dl className="reportPosition">
          <div><dt>Cash: counted vs expected</dt><dd>{amount(cash)} vs {amount(expectedCash)}{Math.abs(cashVariance) >= 0.005 && ` (${cashVariance > 0 ? "+" : ""}${cashVariance.toLocaleString()})`}</dd></div>
          <div><dt>{combined?.sale_mpesa_to === "AGENT_LINE" ? "Agent line" : "Float"}: entered vs expected</dt><dd>{amount(float)} vs {amount(expectedFloat)}{float !== "" && Math.abs(floatVariance) >= 0.005 && ` (${floatVariance > 0 ? "+" : ""}${floatVariance.toLocaleString()})`}</dd></div>
          <div><dt>{combined ? "The agency's money in operation now vs at opening" : "Money in operation now vs at opening"}</dt><dd><strong>{amount(total)}</strong> vs {amount(opening)} ({total - opening >= 0 ? "+" : ""}{(total - opening).toLocaleString()})</dd></div>
        </dl>
        {variance && <FormField label="Why is there a difference? (required)" name="reason" required value={reason}
          onChange={(event) => setReason(event.target.value)} />}
        <div className="actionRow">
          <button>Close shift</button>
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
        </div>
      </fieldset>
      <FormError title="Could not close the shift." message={error} />
    </form>
  );
}
// A manager sets the cash and float to what they really are, with a reason. The difference is recorded as an
// adjustment (never an edit), so the books and the monthly report show it, and it can be reversed like any other.
function CorrectMoney({ dashboard, onDone, onCancel }) {
  const [cash, setCash] = useState(String(Number(dashboard.cash)));
  const [float, setFloat] = useState(String(Number(dashboard.float)));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cashChange = Number((Number(cash || 0) - Number(dashboard.cash)).toFixed(2));
  const floatChange = Number((Number(float || 0) - Number(dashboard.float)).toFixed(2));
  const total = Number(cash || 0) + Number(float || 0);
  const change = cashChange + floatChange;
  const changed = cashChange !== 0 || floatChange !== 0;
  const submit = async (event) => {
    event.preventDefault();
    if (!changed) return setError("Change the cash or the float to what it should be.");
    if (!(await confirmAction({ title: `Correct the money in operation to ${amount(total)}?`,
      text: `Cash ${signedFigure(cashChange)}, float ${signedFigure(floatChange)}. It is recorded as an adjustment with your reason.`,
      confirmButtonText: "Correct it" }))) return;
    setBusy(true);
    setError("");
    try {
      await postMpesaTransaction({ session: dashboard.session.id, transaction_type: "ADJUSTMENT", amount: (Math.abs(cashChange) + Math.abs(floatChange)).toFixed(2),
        cash_delta: cashChange.toFixed(2), float_delta: floatChange.toFixed(2), notes: reason, idempotency_key: crypto.randomUUID() });
      await onDone();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="formCard shiftForm" onSubmit={(event) => void submit(event)} aria-label="Correct money in operation">
      <h2>Correct money in operation</h2>
      <p className="muted">Enter what the cash and float really are. Lower them to take money out, raise them to add it.</p>
      <fieldset disabled={busy}>
        <FormField label="Cash should be" name="cash" type="number" min="0" step="0.01" required value={cash} onChange={(event) => setCash(event.target.value)} />
        <FormField label="Float should be" name="float" type="number" min="0" step="0.01" required value={float} onChange={(event) => setFloat(event.target.value)} />
        <dl className="reportPosition">
          <div><dt>Money in operation: now vs corrected</dt><dd>{amount(dashboard.in_operation.total)} vs <strong>{amount(total)}</strong>{changed && ` (${signedFigure(change)})`}</dd></div>
        </dl>
        <FormField label="Reason" name="reason" required maxLength={240} placeholder="e.g. opening cash was counted twice" value={reason} onChange={(event) => setReason(event.target.value)} />
        <div className="actionRow">
          <button disabled={!changed}>Correct money in operation</button>
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
        </div>
      </fieldset>
      <FormError title="Could not correct the money in operation." message={error} />
    </form>
  );
}
export function MpesaDashboardPage() {
  const { user } = useAuth();
  // A new business day starts at 00:00: reload everything so today's lists, balances and warnings start fresh.
  useNewBusinessDay(() => window.location.reload());
  const canAddOutlet = Boolean(user?.permissions?.includes("mpesa.add_mpesaoutlet"));
  const canChangeOutlet = Boolean(user?.permissions?.includes("mpesa.change_mpesaoutlet"));
  const canDeleteOutlet = Boolean(user?.permissions?.includes("mpesa.delete_mpesaoutlet"));
  const canPost = Boolean(user?.permissions?.includes("mpesa.add_mpesatransaction"));
  const [addingOutlet, setAddingOutlet] = useState(false);
  const [dashboard, setDashboard] = useState();
  const [outlets, setOutlets] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [error, setError] = useState("");
  const [openingCount, setOpeningCount] = useState(emptyCount);
  const [openingOutlet, setOpeningOutlet] = useState("");
  const [openingFloat, setOpeningFloat] = useState("");
  const [opening, setOpening] = useState(emptyOpening);
  const [openingCommission, setOpeningCommission] = useState("");
  // The opening form starts from what the outlet last recorded, so the operator only changes what is different.
  const prefilledFor = useRef(null);
  const prefill = (outlet) => {
    prefilledFor.current = outlet?.id ?? null;
    const money = expectedCount(outlet?.money_in_operation);
    setOpeningCount(money?.cash == null ? emptyCount() : countFrom(money.cash_count, money.cash));
    setOpeningFloat(money?.float == null ? "" : String(Number(money.float)));
    setOpeningCommission(money?.commission_balance == null ? "" : String(Number(money.commission_balance)));
    setOpening(emptyOpening());
  };
  const canRecordCommission = Boolean(user?.permissions?.includes("mpesa.add_mpesacommissionentry"));
  const [closing, setClosing] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const canCorrect = Boolean(user?.permissions?.includes("mpesa.reverse_mpesa_transaction"));
  const load = async () => {
    try {
      const [summary, outletRows, entries] = await Promise.all([
        getMpesaDashboard(),
        getMpesaOutlets(),
        getMpesaTransactions(),
      ]);
      setDashboard(summary);
      setOutlets(outletRows);
      if (!summary.session && prefilledFor.current == null) prefill(outletRows.find((outlet) => outlet.active));
      setTransactions(entries);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  // Other staff record on the same desk: refresh after changes, on return to the tab, and every 20 seconds.
  useLiveRefresh(load, { pollMs: 20000 });
  if (error) return <ErrorState message={error} retry={load} />;
  if (!dashboard) return <Loading />;
  // Only the open shift's transactions are shown; closing it starts the desk afresh. Closed shifts stay on record (Past shifts).
  // A reversed transaction and its reversal cancel out, so neither is listed (both stay on record and in the monthly report).
  const reversedIds = new Set(transactions.filter((entry) => entry.reversal_of).map((entry) => entry.reversal_of));
  const shiftTransactions = dashboard.session ? transactions.filter((entry) => entry.session === dashboard.session.id
    && entry.transaction_type !== "REVERSAL" && !reversedIds.has(entry.id)) : [];
  const addOutlet = async (body) => {
    await createMpesaOutlet(body);
    setAddingOutlet(false);
    await load();
  };
  const activeOutlets = outlets.filter((outlet) => outlet.active);
  const openingAt = activeOutlets.find((outlet) => String(outlet.id) === openingOutlet) || activeOutlets[0];
  const lastClose = expectedCount(openingAt?.money_in_operation);
  const open = async (event) => {
    event.preventDefault();
    const gaps = openingGaps(lastClose, countTotal(openingCount), openingFloat, opening);
    const commission = opening.commission && gaps.extraFloat > 0;
    if (
      !(await confirmAction({
        title: "Open this M-Pesa shift?",
        text: `Opening balances will be recorded for this agency session.${commission
          ? ` ${businessCurrency()} ${Number(opening.commissionAmount).toLocaleString()} of the float is recorded as Safaricom commission.` : ""}`,
        confirmButtonText: "Open shift",
      }))
    )
      return;
    try {
      await openMpesaSession({
        outlet: openingAt?.id,
        opening_cash: countTotal(openingCount).toFixed(2),
        opening_float: openingFloat,
        cash_count: countPayload(openingCount),
        commission_balance: openingCommission,
        difference_reason: gaps.cash || gaps.float ? opening.reason : "",
        ...(commission ? { commission: { period: `${opening.month}-01`, amount: opening.commissionAmount, idempotency_key: crypto.randomUUID() } } : {}),
      });
    } catch (err) {
      await showError("Could not open the shift.", err.message);
      return;
    }
    prefilledFor.current = null;  // the next opening starts from what this shift closes with
    await load();
  };
  const rebalance = async (type) => {
    if (!dashboard.session) return;
    const topUp = type === "FLOAT_TOPUP";
    const values = await askForm({
      title: topUp ? "Record float top-up" : "Record cash rebalance",
      text: topUp
        ? "Electronic float added to the agent line. Say where the money came from: cash from the drawer turned into float lowers the cash by the same amount; money from outside the agency only adds float."
        : "Cash brought into the agency drawer from outside (for example from the bank or the owner).",
      confirmButtonText: "Record transaction",
      fields: [
        ...(topUp ? [{ name: "source", label: "Where the money came from", type: "select", required: true,
          options: [["", "Choose…"], ...TOPUP_SOURCES] }] : []),
        { name: "amount", label: topUp ? "Float bought" : "Cash received", type: "number", required: true },
        { name: "reference", label: "Reference, e.g. the M-Pesa code" },
        { name: "notes", label: "Source or notes", placeholder: topUp ? "e.g. bought from the bank agent" : "e.g. from the owner" },
      ],
    });
    if (!values) return;
    try {
      await postMpesaTransaction({
        session: dashboard.session.id,
        transaction_type: type,
        amount: values.amount,
        ...(topUp ? { paid_by: values.source } : {}),
        provider_reference: values.reference || undefined,
        notes: values.notes,
        idempotency_key: crypto.randomUUID(),
      });
    } catch (err) {
      await showError(topUp ? "Could not record the float top-up." : "Could not record the cash rebalance.", err.message);
      return;
    }
    await load();
  };
  const close = async (body) => {
    await reconcileMpesaSession(dashboard.session.id, body);
    setClosing(false);
    await load();
  };
  return (
    <>
      <span className="eyebrow">Agent money (kept separate from the shop)</span>
      <h1>M-Pesa Agent</h1>
      <p className="privacyNotice">
        Agency deposits, withdrawals and airtime sales move cash and electronic float. Their
        principal is never sales revenue; only commission is.
      </p>
      <div className="metrics">
        <MetricCard label="Money in operation">
          {amount(dashboard.in_operation.total)}
          {dashboard.session && <small className="muted"> · opened with {amount(dashboard.in_operation.opening)}</small>}
        </MetricCard>
        <MetricCard label="Current cash">{businessCurrency()} {dashboard.cash}</MetricCard>
        <MetricCard label="Current float">{businessCurrency()} {dashboard.float}</MetricCard>
        <MetricCard label="Today's deposits">
          {businessCurrency()} {dashboard.deposits}
        </MetricCard>
        <MetricCard label="Today's withdrawals">
          {businessCurrency()} {dashboard.withdrawals}
        </MetricCard>
        <MetricCard label="Today's airtime sold">
          {businessCurrency()} {dashboard.airtime ?? 0}
        </MetricCard>
        <MetricCard label="Transactions">
          {dashboard.transaction_count}
        </MetricCard>
        {dashboard.commission_shift && <MetricCard label="Commission this shift">
          {amount(dashboard.commission_shift.earned)}
          {dashboard.commission_shift.unknown > 0 && <small className="muted"> · {dashboard.commission_shift.unknown} not worked out yet</small>}
        </MetricCard>}
        {dashboard.commission_month && <MetricCard label={`${dashboard.commission_month.label} commission, expected`}>
          {amount(dashboard.commission_month.forecast)}
          <small className="muted"> · {amount(dashboard.commission_month.so_far)} so far, {dashboard.commission_month.days_left} {dashboard.commission_month.days_left === 1 ? "working day" : "working days"} left</small>
        </MetricCard>}
      </div>
      {dashboard.session && <ShiftChart transactions={shiftTransactions} openedAt={dashboard.session.opened_at} />}
      <MpesaAnalysis refreshKey={dashboard.transaction_count} />
      <MonthlyReport />
      <PastShifts />
      <section className="outletSection" aria-labelledby="outlets-heading">
        <div className="sectionHeading">
          <h2 id="outlets-heading">Outlets</h2>
          {canAddOutlet && !addingOutlet && <button type="button" className="secondary" onClick={() => setAddingOutlet(true)}>Add outlet</button>}
        </div>
        <OutletCards outlets={outlets} canChange={canChangeOutlet} canDelete={canDeleteOutlet} canRead={canPost} onChanged={load} />
        {canAddOutlet && addingOutlet && <OutletForm onSave={addOutlet} onCancel={() => setAddingOutlet(false)} />}
      </section>
      {!dashboard.session ? (
        <>
        <form
          className="formCard shiftForm"
          onSubmit={(event) => void open(event)}
        >
          <h2>Open M-Pesa shift</h2>
          {!outlets.length && (
            <p>
              {canAddOutlet
                ? "Add your M-Pesa agent outlet (Add outlet, above) before opening a shift."
                : "No active outlet exists. Ask the business owner to add one on this page."}
            </p>
          )}
          <label>
            Outlet
            <select name="outlet" required value={openingAt ? String(openingAt.id) : ""}
              onChange={(event) => { setOpeningOutlet(event.target.value); prefill(activeOutlets.find((outlet) => String(outlet.id) === event.target.value)); }}>
              {activeOutlets.map((outlet) => (
                <option key={outlet.id} value={outlet.id}>
                  {outlet.display_name}
                </option>
              ))}
            </select>
          </label>
          {lastClose?.combined && <p className="muted">Count all the money, the agency's and the business's together: the app knows from
            the sales how much of it is the business's ({amount(lastClose.combined.business_cash)} in the drawer
            {lastClose.combined.sale_mpesa_to === "AGENT_LINE" ? `, ${amount(lastClose.combined.business_line)} on the agent line` : ""}).</p>}
          <CashCounter count={openingCount} onChange={setOpeningCount} legend={lastClose?.combined ? "Opening cash: count all the cash in the drawer" : "Opening cash: count the drawer"} />
          <FormField
            label={lastClose?.combined?.sale_mpesa_to === "AGENT_LINE" ? "Opening: all the money on the agent line" : "Opening float"}
            name="opening_float"
            type="number"
            min="0"
            step="0.01"
            required
            value={openingFloat}
            onChange={(event) => setOpeningFloat(event.target.value)}
          />
          <FormField
            label={`Commission balance now (${businessCurrency()})`}
            name="commission_balance"
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            required
            placeholder="As shown on the agent line"
            value={openingCommission}
            onChange={(event) => setOpeningCommission(event.target.value)}
          />
          <p className="muted">{lastClose?.commission_balance == null
            ? "Read the commission balance off the agent line. The shift's first transaction is measured from it."
            : Number(openingCommission) < Number(lastClose.commission_balance) && openingCommission !== ""
              ? `Lower than ${amount(lastClose.commission_balance)}: Safaricom paid the commission out since then.`
              : Number(lastClose.commission_worked_out) > 0 || Number(lastClose.commission_paid_out) > 0
                ? `Filled in with ${amount(lastClose.commission_balance)}: ${commissionSince(lastClose).replace(/^Last/, "last")}. Change it if the agent line shows a different balance.`
                : `Filled in with the last reading, ${amount(lastClose.commission_balance)}. Change it if the agent line shows a different balance.`}</p>
          <OpeningCheck last={lastClose} cash={countTotal(openingCount)} electronicFloat={openingFloat} opening={opening}
            onChange={setOpening} canRecordCommission={canRecordCommission} />
          <button disabled={!outlets.length}>Open shift</button>
        </form>
        </>
      ) : (
        <>
          {businessDate(dashboard.session.opened_at) !== businessDate() && !closing && (
            <div className="subscriptionBanner warn staleShift" role="alert">
              <span>This shift was opened on {businessDate(dashboard.session.opened_at)} and is still open. Count the cash and
                float and close it; today's shift can be opened straight after.</span>
              <button type="button" onClick={() => setClosing(true)}>Close previous shift</button>
            </div>
          )}
          <div className="deskActions">
            <button onClick={() => void rebalance("FLOAT_TOPUP")}>
              Float top-up
            </button>
            <button onClick={() => void rebalance("CASH_REBALANCE")}>
              Cash rebalance
            </button>
            {canCorrect && <button className="secondary" onClick={() => setCorrecting(true)}>
              Correct money in operation
            </button>}
            <button className="secondary" onClick={() => setClosing(true)}>
              Close & reconcile shift
            </button>
          </div>
          {correcting && <CorrectMoney dashboard={dashboard} onCancel={() => setCorrecting(false)} onDone={async () => { setCorrecting(false); await load(); }} />}
          {closing && <CloseShift dashboard={dashboard} onClose={close} onCancel={() => setClosing(false)} />}
          <div className="deskGrid mpesaDesk">
            <MpesaDepositForm
              sessionId={dashboard.session.id}
              availableCash={dashboard.cash}
              availableFloat={dashboard.float}
              onPosted={load}
            />
            <MpesaWithdrawalForm
              sessionId={dashboard.session.id}
              availableCash={dashboard.cash}
              availableFloat={dashboard.float}
              onPosted={load}
            />
            <MpesaAirtimeForm
              sessionId={dashboard.session.id}
              availableCash={dashboard.cash}
              availableFloat={dashboard.float}
              onPosted={load}
            />
          </div>
        </>
      )}
      <CustomerTransactionList title="Deposits" type="CUSTOMER_DEPOSIT" transactions={shiftTransactions} onChanged={load} />
      <CustomerTransactionList title="Withdrawals" type="CUSTOMER_WITHDRAWAL" transactions={shiftTransactions} onChanged={load} />
      <CustomerTransactionList title="Airtime sold" type="AIRTIME_SALE" transactions={shiftTransactions} onChanged={load} />
      <section>
        <h2>Agency transactions this shift</h2>
        {!shiftTransactions.length ? (
          <Empty>{dashboard.session ? "No transactions in this shift yet." : "No shift open. Open a shift to start recording."}</Empty>
        ) : (
          <div className="table ledgerTable agencyLedger">
            <div>
              <b>Reference</b>
              <b>Type</b>
              <b>Amount</b>
              <b>Cash effect</b>
              <b>Float effect</b>
              <b>Action</b>
            </div>
            {shiftTransactions.map((entry) => (
              <div key={entry.id}>
                <span>
                  {entry.provider_reference || entry.internal_reference}
                </span>
                <span>{entry.transaction_type.replaceAll("_", " ")}</span>
                <span>{businessCurrency()} {figure(entry.amount)}</span>
                <span>{signedFigure(entry.cash_delta)}</span>
                <span>{signedFigure(entry.float_delta)}</span>
                <span className="agencyActions">
                  {user?.permissions?.includes("mpesa.reverse_mpesa_transaction") && <CorrectTransaction entry={entry} onDone={load} />}
                  {/* Money moved to or from an investment is undone on the Investments page, which fixes both sides. */}
                  {!["REVERSAL", "INVESTMENT"].includes(entry.transaction_type) &&
                    !entry.reversal_of && (
                      <button
                        className="danger"
                        onClick={async () => {
                          const values = await askForm({
                            title: "Cancel this M-Pesa transaction?",
                            text: "This cancels it and puts the cash and float back. The original stays in the history.",
                            confirmButtonText: "Cancel transaction",
                            fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. entered twice" }],
                          });
                          if (!values) return;
                          try {
                            await reverseMpesaTransaction(entry.id, values.reason);
                          } catch (err) {
                            await showError("Could not reverse the transaction.", err.message);
                            return;
                          }
                          await load();
                        }}
                      >
                        Reverse
                      </button>
                    )}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
