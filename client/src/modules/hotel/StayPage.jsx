import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";
import { addDays, can, day, isoDay, METHODS, methodName, money } from "./shared";
import "./hotel.css";

const KIND = { NIGHT: "Room", TILL: "From the till", EXTRA: "Extra" };

// One guest's stay: their details, their bill (nights, food and drinks charged to the room, extras), what they paid, and
// everything the front desk does with it: check in, take money, add a charge, move or extend, check out, cancel.
export function StayPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const [stay, setStay] = useState(null);
  const [error, setError] = useState("");
  const [panel, setPanel] = useState("");
  const load = useCallback(() => api(`/api/v1/hotel/stays/${id}/`).then((data) => { setStay(data); setError(""); }).catch((e) => setError(e.message)), [id]);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load);
  if (error && !stay) return <ErrorState message={error} retry={load} />;
  if (!stay) return <Loading />;
  const bill = stay.bill;
  const act = async (action, body) => {
    const data = await api(`/api/v1/hotel/stays/${stay.id}/${action}/`, { method: "POST", body: JSON.stringify(body || {}) });
    setStay(data); setPanel("");
  };
  const open = ["BOOKED", "IN"].includes(stay.status);
  const desk = can(user, "hotel.change_stay");
  const takes = can(user, "hotel.add_staydeposit");
  const panels = [
    stay.status === "BOOKED" && desk && ["check-in", "Check in"],
    stay.status === "IN" && desk && ["check-out", "Check out"],
    open && takes && ["pay", stay.status === "BOOKED" ? "Take a deposit" : "Take a payment"],
    stay.status === "IN" && desk && ["extra", "Add a charge"],
    open && desk && ["change", stay.status === "IN" ? "Move or extend" : "Change booking"],
    stay.status === "BOOKED" && desk && ["cancel", "Cancel booking"],
  ].filter(Boolean);
  return <div className="hotelPage">
    <header className="hotelHead">
      <div><span className="eyebrow">{stay.number} · {stay.status_label}</span><h1>{stay.guest}</h1>
        <p className="muted">Room {stay.room.number} ({stay.room.type}) · {day(stay.arrival)} → {day(stay.departure)} · {stay.guests} {stay.guests === 1 ? "guest" : "guests"} · {money(stay.rate)} a night
          {stay.phone ? ` · ${stay.phone}` : ""}{stay.id_number ? ` · ID ${stay.id_number}` : ""}</p>
        {stay.note && <p className="muted">{stay.note}</p>}</div>
      <div className="actionRow"><Link className="button secondary" to="/admin/rooms">Front desk</Link></div>
    </header>

    <dl className="hotelFigures">
      <div><dt>Charged so far</dt><dd>{money(bill.total)}</dd></div>
      <div><dt>Paid</dt><dd>{money(bill.paid)}</dd></div>
      {Number(bill.owing) > 0 && <div className="owes"><dt>Still owed</dt><dd>{money(bill.owing)}</dd></div>}
      {Number(bill.held) > 0 && <div className="owns"><dt>Paid ahead, not used yet</dt><dd>{money(bill.held)}</dd></div>}
      {Number(bill.owing) <= 0 && Number(bill.held) <= 0 && <div><dt>Balance</dt><dd>Settled</dd></div>}
    </dl>

    {panels.length > 0 && <div className="hotelTabs" role="tablist" aria-label="What to do">
      {panels.map(([key, name]) => <button type="button" role="tab" key={key} aria-selected={panel === key} className={panel === key ? "" : "secondary"}
        onClick={() => setPanel(panel === key ? "" : key)}>{name}</button>)}
    </div>}
    {panel === "check-in" && <CheckInForm stay={stay} act={act} onClose={() => setPanel("")} />}
    {panel === "check-out" && <CheckOutForm stay={stay} user={user} act={act} onClose={() => setPanel("")} />}
    {panel === "pay" && <PaymentForm stay={stay} act={act} onClose={() => setPanel("")} />}
    {panel === "extra" && <ExtraForm act={act} onClose={() => setPanel("")} />}
    {panel === "change" && <ChangeForm stay={stay} onSaved={(data) => { setStay(data); setPanel(""); }} onClose={() => setPanel("")} />}
    {panel === "cancel" && <CancelForm stay={stay} act={act} onClose={() => setPanel("")} />}

    <h2>Bill</h2>
    {bill.charges.length === 0 ? <p className="muted">{stay.status === "BOOKED" ? "Nights are charged from check-in: the first on arrival, then one each morning the guest is still in after the check-out time." : "Nothing charged."}</p>
      : <div className="tableWrap"><table className="billTable">
        <thead><tr><th>Date</th><th>What</th><th>For</th><th>Amount</th></tr></thead>
        <tbody>{bill.charges.flatMap((charge) => charge.lines.map((line, index) => <tr key={`${charge.id}-${index}`}>
          <td>{index === 0 ? day(charge.night || charge.at) : ""}</td>
          <td>{line.name}{Number(line.quantity) !== 1 ? ` × ${Number(line.quantity)}` : ""}</td>
          <td className="muted">{index === 0 ? KIND[charge.kind] : ""}</td>
          <td>{money(line.amount)}</td>
        </tr>))}</tbody>
        <tfoot><tr><td colSpan={3}>Total</td><td>{money(bill.total)}</td></tr></tfoot>
      </table></div>}

    {bill.payments.length > 0 && <>
      <h2>Payments</h2>
      <ul className="hotelList">{bill.payments.map((p) => <li key={p.id}>
        <div><b>{money(p.amount)}</b><small className="muted">{methodName(p.method)}{p.reference ? ` · ${p.reference}` : ""} · {day(p.at)}</small></div>
        <small className="muted">{Number(p.refunded) > 0 ? `${money(p.refunded)} given back` : Number(p.used) < Number(p.amount) ? `${money(Number(p.amount) - Number(p.used))} not used yet` : "Used"}</small>
      </li>)}</ul>
    </>}
  </div>;
}

function useSubmit(run) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true); setError("");
    try { await run(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return { busy, error, submit };
}

function MoneyFields({ value, onChange, label = "Amount", required = true }) {
  const set = (changes) => onChange({ ...value, ...changes });
  return <>
    <label>{label}<input type="number" min="0" step="0.01" inputMode="decimal" required={required} value={value.amount} onChange={(e) => set({ amount: e.target.value })} /></label>
    <label>Paid by<select value={value.method} onChange={(e) => set({ method: e.target.value })}>{METHODS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
    {value.method !== "CASH" && value.amount !== "" && <label>{value.method === "MPESA" ? "M-Pesa code" : "Bank reference"}<TextBox required value={value.reference} onChange={(e) => set({ reference: e.target.value })} maxLength={100} /></label>}
  </>;
}

function CheckInForm({ stay, act, onClose }) {
  const [idNumber, setIdNumber] = useState(stay.id_number);
  const [paid, setPaid] = useState({ amount: "", method: "CASH", reference: "" });
  const { busy, error, submit } = useSubmit(() => act("check-in", { id_number: idNumber, ...(paid.amount ? { paid: paid.amount, method: paid.method, reference: paid.reference } : {}) }));
  const early = stay.arrival > isoDay(new Date());
  return <form className="hotelForm" onSubmit={(e) => void submit(e)} aria-label="Check in">
    {early && <p className="muted">Booked from {day(stay.arrival)}: checking in now starts the stay today.</p>}
    <fieldset disabled={busy} className="chamaPlainFieldset"><div className="formGrid">
      <label>ID or passport number<TextBox value={idNumber} onChange={(e) => setIdNumber(e.target.value)} maxLength={40} /></label>
      <MoneyFields value={paid} onChange={setPaid} label="Paid now (optional)" required={false} />
    </div></fieldset>
    <p className="muted">The first night, {money(stay.rate)}, is charged on checking in.</p>
    <FormError title="Could not check the guest in." message={error} />
    <div className="actionRow"><button disabled={busy}>Check in</button><button type="button" className="secondary" onClick={onClose}>Close</button></div>
  </form>;
}

function PaymentForm({ stay, act, onClose }) {
  const owing = Number(stay.bill.owing);
  const [paid, setPaid] = useState({ amount: owing > 0 ? String(owing) : "", method: "CASH", reference: "" });
  const { busy, error, submit } = useSubmit(() => act("payments", paid));
  return <form className="hotelForm" onSubmit={(e) => void submit(e)} aria-label="Take a payment">
    <fieldset disabled={busy} className="chamaPlainFieldset"><div className="formGrid"><MoneyFields value={paid} onChange={setPaid} /></div></fieldset>
    <p className="muted">It pays what the guest owes now; anything more is kept for their next nights and given back if not used.</p>
    <FormError title="Could not take the payment." message={error} />
    <div className="actionRow"><button disabled={busy}>Record payment</button><button type="button" className="secondary" onClick={onClose}>Close</button></div>
  </form>;
}

function ExtraForm({ act, onClose }) {
  const [extra, setExtra] = useState({ description: "", amount: "" });
  const [key] = useState(() => crypto.randomUUID?.() || String(Date.now()));
  const { busy, error, submit } = useSubmit(() => act("extras", { ...extra, idempotency_key: key }));
  return <form className="hotelForm" onSubmit={(e) => void submit(e)} aria-label="Add a charge">
    <fieldset disabled={busy} className="chamaPlainFieldset"><div className="formGrid">
      <label>What it is for<TextBox required value={extra.description} onChange={(e) => setExtra({ ...extra, description: e.target.value })} maxLength={120} placeholder="Laundry, extra bed, late check-out" /></label>
      <label>Amount<input type="number" min="0" step="0.01" inputMode="decimal" required value={extra.amount} onChange={(e) => setExtra({ ...extra, amount: e.target.value })} /></label>
    </div></fieldset>
    <p className="muted">Food and drinks are charged from the till: choose <b>Room</b> when taking payment there.</p>
    <FormError title="Could not add the charge." message={error} />
    <div className="actionRow"><button disabled={busy}>Add to the bill</button><button type="button" className="secondary" onClick={onClose}>Close</button></div>
  </form>;
}

function CheckOutForm({ stay, user, act, onClose }) {
  const owing = Number(stay.bill.owing), held = Number(stay.bill.held);
  const [paid, setPaid] = useState({ amount: owing > 0 ? String(owing) : "", method: "CASH", reference: "" });
  const [giveBack, setGiveBack] = useState("CASH");
  const [leaveOwing, setLeaveOwing] = useState(false);
  const after = owing - Number(paid.amount || 0);
  const { busy, error, submit } = useSubmit(() => act("check-out", {
    ...(owing > 0 && paid.amount ? { payment: paid } : {}), ...(held > 0 || after < 0 ? { give_back_by: giveBack } : {}), leave_owing: leaveOwing }));
  return <form className="hotelForm" onSubmit={(e) => void submit(e)} aria-label="Check out">
    <p>Nights are brought up to date first: a guest still in after the check-out time pays that day's night too.</p>
    {owing > 0 && <>
      <p><b>{stay.guest} owes {money(owing)}.</b></p>
      <fieldset disabled={busy || leaveOwing} className="chamaPlainFieldset"><div className="formGrid"><MoneyFields value={paid} onChange={setPaid} label="Paid now" required={!leaveOwing} /></div></fieldset>
      {can(user, "commerce.change_sale") && <label className="checkLine"><input type="checkbox" checked={leaveOwing} onChange={(e) => setLeaveOwing(e.target.checked)} /> Let them leave owing it (it stays on their customer account)</label>}
    </>}
    {(held > 0 || after < 0) && <label>{held > 0 ? `${money(held)} paid ahead is not used: give it back by` : "Give the extra back by"}
      <select value={giveBack} onChange={(e) => setGiveBack(e.target.value)}>{METHODS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>}
    <FormError title="Could not check the guest out." message={error} />
    <div className="actionRow"><button disabled={busy}>Check out</button><button type="button" className="secondary" onClick={onClose}>Close</button></div>
  </form>;
}

function ChangeForm({ stay, onSaved, onClose }) {
  const [rooms, setRooms] = useState(null);
  const [form, setForm] = useState({ room: String(stay.room.id), arrival: stay.arrival, departure: stay.departure, rate: String(Number(stay.rate)),
    guests: stay.guests, phone: stay.phone, id_number: stay.id_number });
  useEffect(() => { api("/api/v1/hotel/rooms/").then((data) => setRooms(data.rooms)).catch(() => setRooms([])); }, []);
  const set = (changes) => setForm((current) => ({ ...current, ...changes }));
  const { busy, error, submit } = useSubmit(async () => onSaved(await api(`/api/v1/hotel/stays/${stay.id}/`, { method: "PATCH",
    body: JSON.stringify({ ...form, room: form.room !== String(stay.room.id) ? form.room : undefined, arrival: stay.status === "BOOKED" ? form.arrival : undefined }) })));
  return <form className="hotelForm" onSubmit={(e) => void submit(e)} aria-label="Change the stay">
    <fieldset disabled={busy} className="chamaPlainFieldset"><div className="formGrid">
      <label>Room<select value={form.room} onChange={(e) => set({ room: e.target.value })}>
        {(rooms || [{ id: stay.room.id, number: stay.room.number, type: stay.room.type }]).map((r) => <option key={r.id} value={r.id}>{r.number} · {r.type}</option>)}
      </select></label>
      {stay.status === "BOOKED" && <label>Arriving<input type="date" value={form.arrival} onChange={(e) => set({ arrival: e.target.value })} /></label>}
      <label>Leaving<input type="date" min={addDays(stay.status === "IN" ? isoDay(new Date()) : form.arrival, 1)} value={form.departure} onChange={(e) => set({ departure: e.target.value })} /></label>
      <label>Price a night from now<input type="number" min="0" step="0.01" value={form.rate} onChange={(e) => set({ rate: e.target.value })} /></label>
      <label>Guests<input type="number" min="1" value={form.guests} onChange={(e) => set({ guests: e.target.value })} /></label>
      <label>Phone<TextBox value={form.phone} onChange={(e) => set({ phone: e.target.value })} maxLength={30} /></label>
      <label>ID or passport number<TextBox value={form.id_number} onChange={(e) => set({ id_number: e.target.value })} maxLength={40} /></label>
    </div></fieldset>
    <p className="muted">Nights already charged keep their price. Moving a guest marks their old room for cleaning.</p>
    <FormError title="Could not change the stay." message={error} />
    <div className="actionRow"><button disabled={busy}>Save</button><button type="button" className="secondary" onClick={onClose}>Close</button></div>
  </form>;
}

function CancelForm({ stay, act, onClose }) {
  // An employee says why: the business owner sees it with what staff undid.
  const employee = useAuth().user?.roles?.[0] === "EMPLOYEE";
  const held = Number(stay.bill.held);
  const [form, setForm] = useState({ reason: "", no_show: false, keep_paid: false, give_back_by: "CASH" });
  const { busy, error, submit } = useSubmit(() => act("cancel", form));
  return <form className="hotelForm" onSubmit={(e) => void submit(e)} aria-label="Cancel the booking">
    <fieldset disabled={busy} className="chamaPlainFieldset"><div className="formGrid">
      <label className="checkLine"><input type="checkbox" checked={form.no_show} onChange={(e) => setForm({ ...form, no_show: e.target.checked })} /> The guest did not come</label>
      <label className="wide">Reason{employee ? " (the business owner sees it)" : ""}<TextBox value={form.reason} required={employee} onChange={(e) => setForm({ ...form, reason: e.target.value })} maxLength={200} /></label>
      {held > 0 && <label>{money(held)} was paid<select value={form.keep_paid ? "KEEP" : form.give_back_by} onChange={(e) => setForm({ ...form, keep_paid: e.target.value === "KEEP", give_back_by: e.target.value === "KEEP" ? form.give_back_by : e.target.value })}>
        {METHODS.map(([id, name]) => <option key={id} value={id}>Give it back by {name.toLowerCase()}</option>)}
        <option value="KEEP">Keep it as the booking's price</option>
      </select></label>}
    </div></fieldset>
    <FormError title="Could not cancel the booking." message={error} />
    <div className="actionRow"><button disabled={busy}>{form.no_show ? "Mark as not come" : "Cancel booking"}</button><button type="button" className="secondary" onClick={onClose}>Close</button></div>
  </form>;
}
