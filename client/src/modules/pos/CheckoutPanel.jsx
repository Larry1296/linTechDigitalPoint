import { useEffect, useState } from "react";
import { Banknote, BedDouble, CheckCircle2, Clock, Landmark, Smartphone, UserRound, X } from "lucide-react";
import { api } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";
import { confirmAction } from "../../core/ui/alerts";
import { FormError } from "../../components/forms/FormNotice";
import { PromptStatus, shownPhone } from "./MpesaPrompt";
import { TextBox } from "../../components/forms/TextBox";
import { CustomerChooser } from "./CustomerChooser";

const POLL_MS = 2500;
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const time = (value) => new Date(value).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const PAID_WITH = { CASH: "Cash", TILL: "Paid to the till", PROMPT: "M-Pesa prompt", BANK: "Bank", OWED: "Owed by the customer", ROOM: "Charged to the room" };
const OPEN = ["AWAITING", "PART_PAID"];

// How the customer pays a charged basket: cash, the till, a prompt to their phone, bank, or owed by a named customer. Several
// can be combined. The sale is made by the server once the payments cover the amount; till payments and prompts are
// confirmed by Safaricom's own record, never by an amount alone. Owed is always offered: with no customer chosen before
// charging, the one who owes it is chosen (or added) there. In a hotel, a guest who is in may charge it to their room: it
// joins their bill, paid when they check out.
export function CheckoutPanel({ checkout, express, customerPhone, onChange, onDone, onBack, user, customers = [], setCustomers }) {
  const [way, setWay] = useState("CASH");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cashGiven, setCashGiven] = useState("");
  const [code, setCode] = useState("");
  const [phone, setPhone] = useState(shownPhone(customerPhone));
  const [reference, setReference] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [owedBy, setOwedBy] = useState("");
  const [guests, setGuests] = useState(null);
  const [stayId, setStayId] = useState("");
  const rooms = user?.organization?.enabled_modules?.includes("rooms") && user?.permissions?.includes("hotel.view_stay");
  const left = Number(checkout.left);
  const open = OPEN.includes(checkout.status);
  const promptOut = checkout.payments.find((p) => p.method === "PROMPT" && p.status === "PENDING");
  const tillNumber = express?.till_number || "";
  const paybill = express?.paybill || "";

  // Till payments arrive, prompts are answered: follow the checkout until it is finished.
  useEffect(() => {
    if (!open) return undefined;
    const timer = setTimeout(() => {
      api(`/api/v1/commerce/pos/checkouts/${checkout.id}/`).then(onChange).catch(() => onChange({ ...checkout }));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [checkout, open, onChange]);
  useEffect(() => { if (checkout.status === "COMPLETED") onDone(checkout); }, [checkout, onDone]);

  // Returns whether the server took it.
  const send = async (path, body) => {
    if (busy) return false;
    setBusy(true); setError("");
    try {
      onChange(await api(`/api/v1/commerce/pos/checkouts/${checkout.id}/${path}`, { method: "POST", body: JSON.stringify(body || {}) }));
      setCashGiven(""); setCode(""); setReference("");
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally { setBusy(false); }
  };
  const pay = (body) => send("pay/", body);
  useEffect(() => {
    if (way !== "ROOM" || guests) return;
    api("/api/v1/hotel/stays/in-house/").then(setGuests).catch((e) => { setGuests([]); setError(e.message); });
  }, [way, guests]);
  const cancel = async () => {
    const received = checkout.payments.some((p) => p.status === "CONFIRMED" && !["CASH", "OWED", "ROOM"].includes(p.method));
    if (!(await confirmAction({ title: "Cancel this checkout?",
      text: received ? "Money has already reached the business for it. A manager cancels it, and the M-Pesa payment is kept for a refund."
        : "Nothing is sold. Hand back any cash you took.", confirmButtonText: "Cancel checkout" }))) return;
    if (await send("cancel/", { reason: "Cancelled at the till" })) onBack({ keepBasket: false });
  };
  // Nothing taken yet: the checkout is let go and the basket comes back to be changed.
  const changeBasket = async () => {
    if (await send("cancel/", { reason: "Basket changed" })) onBack({ keepBasket: true });
  };
  const given = Number(cashGiven || 0);
  const change = cashGiven !== "" ? given - left : null;
  const nothingGiven = cashGiven !== "" && given <= 0;

  return <section className="posCheckout" aria-label={`Checkout ${checkout.number}`}>
    <header className="posCheckoutHead">
      <div>
        <span className="eyebrow">{checkout.number} · {checkout.items} {checkout.items === 1 ? "line" : "lines"}</span>
        <p className="posToPay">{checkout.status === "COMPLETED" ? "Paid" : "To pay"} <strong>{money(open ? left : checkout.total)}</strong></p>
        {Number(checkout.paid) > 0 && open && <p className="muted">Total {money(checkout.total)} · paid so far {money(checkout.paid)}</p>}
      </div>
      <div className="posCheckoutHeadActions">
        {/* Nothing taken yet: the items can still be changed (quantities, removing one), then charged again. */}
        {open && checkout.payments.every((p) => p.status !== "CONFIRMED") && <button type="button" className="secondary" onClick={() => void changeBasket()} disabled={busy}>Change items</button>}
        {open && <button type="button" className="secondary" onClick={() => void cancel()} disabled={busy}>Cancel</button>}
      </div>
    </header>

    {checkout.payments.length > 0 && <ul className="posTenders" aria-label="Payments taken">
      {checkout.payments.map((p) => <li key={p.id} className={p.status.toLowerCase()}>
        <span>{p.status === "CONFIRMED" ? <CheckCircle2 size={16} aria-hidden="true" /> : <Clock size={16} aria-hidden="true" />}
          {PAID_WITH[p.method]}{p.reference ? ` · ${p.reference}` : ""}{p.status === "FAILED" ? " · not paid" : ""}</span>
        <strong>{money(p.amount)}</strong>
        {p.change > 0 && <small>Change {money(p.change)}</small>}
        {p.detail && p.method !== "PROMPT" && <small className={p.checked_with_safaricom ? "muted" : "formWarning"}>{p.detail}</small>}
        {p.prompt && <PromptStatus prompt={p.prompt} />}
        {open && ["CONFIRMED", "PENDING"].includes(p.status) && <button type="button" className="posIconButton" disabled={busy}
          aria-label={`Take back ${PAID_WITH[p.method]} ${money(p.amount)}`} onClick={() => void send(`payments/${p.id}/void/`)}><X size={15} /></button>}
      </li>)}
    </ul>}

    {checkout.status === "PAID" && <div className="formNotice" role="alert">
      <p><b>{checkout.problem}</b></p>
      <p>The money is kept with this checkout. Receive the missing stock, then try again; or a manager cancels it and refunds the customer.</p>
      <button type="button" onClick={() => void send("retry/")} disabled={busy}>Try again</button>
    </div>}

    {open && left > 0 && !promptOut && <>
      <div className="posWays" role="tablist" aria-label="How the customer pays">
        {[["CASH", "Cash", Banknote], ["TILL", paybill ? "Paybill" : "Till", Smartphone], ...(express?.ready ? [["PROMPT", "Prompt", Smartphone]] : []),
          ["BANK", "Bank", Landmark], ["OWED", "Owed", UserRound], ...(rooms ? [["ROOM", "Room", BedDouble]] : [])].map(([id, name, Icon]) =>
          <button type="button" role="tab" key={id} aria-selected={way === id} className={way === id ? "on" : ""} onClick={() => { setWay(id); setError(""); }}>
            <Icon size={17} aria-hidden="true" /> {name}
          </button>)}
      </div>

      {way === "CASH" && <form className="posWay" onSubmit={(e) => {
        e.preventDefault();
        // The customer gave nothing: what is left is owed by them, not paid in cash.
        if (nothingGiven) void pay({ method: "OWED", due_date: null, ...(checkout.customer_id ? {} : { customer_id: owedBy }) });
        else void pay({ method: "CASH", cash_given: cashGiven || left });
      }}>
        <label>Cash received<input type="number" min="0" step="0.01" inputMode="decimal" autoFocus value={cashGiven}
          onChange={(e) => setCashGiven(e.target.value)} placeholder={left.toFixed(2)} /></label>
        {nothingGiven
          ? checkout.customer_id ? <p className="muted">The customer gave nothing, so {money(left)} is left owed by them.</p>
            : setCustomers ? <><p className="muted">The customer gave nothing. Choose who owes {money(left)}, or pay another way.</p>
              <CustomerChooser user={user} customers={customers} setCustomers={setCustomers} value={owedBy} onChange={setOwedBy} open /></>
            : <p className="muted">The customer gave nothing. Choose Owed to leave it owed by a named customer, or pay another way.</p>
          : change !== null && (change >= 0 ? <p className="posChange">Give change: <b>{money(change)}</b></p>
            : <p className="muted">{money(-change)} still to pay after this, by any other way.</p>)}
        <button disabled={busy || (nothingGiven && !(checkout.customer_id || owedBy))}>{busy ? "Recording…"
          : nothingGiven ? `Leave ${money(left)} owed by the customer` : `Take ${money(Math.min(given || left, left))} cash`}</button>
      </form>}

      {way === "TILL" && <div className="posWay">
        <p className="posTillAsk">Ask the customer to pay {paybill ? <>Paybill <b>{paybill}</b>, account <b>{checkout.number}</b></> : <>Till <b>{tillNumber || "number"}</b></>}
          {" "}exactly <b>{money(left)}</b>.</p>
        {express?.till_notices ? <>
          {paybill && <p className="muted">A payment to this account number pays the sale by itself.</p>}
          <h3 className="posTillHeading">Payments just received</h3>
          {checkout.till_payments?.length ? <ul className="posTillPayments">
            {checkout.till_payments.map((row) => <li key={row.id} className={Number(row.amount) === left ? "exact" : undefined}>
              <div><b>{money(row.amount)}</b> · {row.code}<br />
                <small className="muted">{time(row.paid_at)} · {row.payer_name || "Customer"} {row.payer_phone}</small></div>
              <button type="button" disabled={busy} onClick={() => void pay({ method: "TILL", incoming_id: row.id })}>This is the customer's</button>
            </li>)}
          </ul> : <p className="muted posTillWaiting"><Clock size={15} aria-hidden="true" /> Waiting for the payment to arrive…</p>}
          <p className="muted">Check the code or the name with the customer's message before choosing: two customers can pay the same amount.</p>
        </> : <p className="formWarning">This till is not connected to Safaricom, so payments cannot be checked here. The code is recorded as typed.
          {express?.can_change ? " Connect it in Settings → M-Pesa payments." : ""}</p>}
        <form className="posInline" onSubmit={(e) => { e.preventDefault(); void pay({ method: "TILL", code }); }}>
          <label>{express?.till_notices ? "Or the code from the customer's message" : "Code from the customer's M-Pesa message"}
            <TextBox value={code} onChange={(e) => setCode(e.target.value)} maxLength={20} placeholder="e.g. SJK4H7XQ2P" autoCapitalize="characters" /></label>
          <button disabled={busy || !code.trim()} className={express?.till_notices ? "secondary" : undefined}>{express?.till_notices ? "Check code" : "Record payment"}</button>
        </form>
        {express?.simulated && <button type="button" className="linkButton" onClick={() => void api("/api/v1/commerce/till-payments/simulate/",
          { method: "POST", body: JSON.stringify({ amount: Math.ceil(left), name: "Test customer" }) }).catch((e) => setError(e.message))}>
          Simulate a till payment (development only)</button>}
      </div>}

      {way === "PROMPT" && <form className="posWay" onSubmit={(e) => { e.preventDefault(); void pay({ method: "PROMPT", phone }); }}>
        <label>Customer's M-Pesa number<TextBox value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" placeholder="0712 345 678" maxLength={16} autoFocus /></label>
        <p className="muted">The customer gets a prompt for {money(left)} and enters their PIN. The sale completes by itself when Safaricom confirms it.</p>
        <button disabled={busy || !phone.trim()}>{busy ? "Sending…" : "Send prompt"}</button>
      </form>}

      {way === "BANK" && <form className="posWay" onSubmit={(e) => { e.preventDefault(); void pay({ method: "BANK", reference }); }}>
        <label>Bank transfer reference<TextBox value={reference} onChange={(e) => setReference(e.target.value)} maxLength={100} /></label>
        <p className="muted">Check that the money is in the business's bank account before recording it.</p>
        <button disabled={busy || !reference.trim()}>Record {money(left)} by bank</button>
      </form>}

      {way === "OWED" && <form className="posWay" onSubmit={(e) => { e.preventDefault();
        void pay({ method: "OWED", due_date: dueDate || null, ...(checkout.customer_id ? {} : { customer_id: owedBy }) }); }}>
        {checkout.customer_id ? <p className="muted">Owed by {customers.find((c) => String(c.id) === String(checkout.customer_id))?.name || "the customer"}.</p>
          : setCustomers ? <CustomerChooser user={user} customers={customers} setCustomers={setCustomers} value={owedBy} onChange={setOwedBy} open />
          : <p className="muted">Choose the customer before charging to leave it owed by them.</p>}
        <label>Due date (optional)<input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} /></label>
        <button disabled={busy || !(checkout.customer_id || owedBy)}>Leave {money(left)} owed by the customer</button>
      </form>}

      {way === "ROOM" && <form className="posWay" onSubmit={(e) => { e.preventDefault(); void pay({ method: "ROOM", stay_id: stayId }); }}>
        {guests === null ? <p className="muted">Finding the guests who are in…</p>
          : guests.length ? <label>Guest's room<select value={stayId} onChange={(e) => setStayId(e.target.value)} autoFocus>
            <option value="">Choose the room</option>
            {guests.map((g) => <option key={g.id} value={g.id}>Room {g.room} · {g.guest}</option>)}
          </select></label>
          : <p className="muted">No guest is checked in, so nothing can be charged to a room.</p>}
        <p className="muted">It goes on the guest's bill, paid when they check out (or from what they paid in advance).</p>
        <button disabled={busy || !stayId}>Charge {money(left)} to the room</button>
      </form>}
    </>}
    {open && promptOut && <p className="muted">Waiting for the customer to answer the prompt. Take it back (×) to pay another way.</p>}
    <FormError title="Could not take the payment." message={error} />
  </section>;
}
