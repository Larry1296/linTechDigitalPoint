import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { BedDouble, Settings2, UserPlus } from "lucide-react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";
import { addDays, can, CONDITIONS, day, isoDay, METHODS, money, nightsBetween, ROOM_STATES } from "./shared";
import "./hotel.css";

// The front desk: every room today (who is in, who arrives, who leaves, what is free and what needs cleaning), and
// booking a guest or checking a walk-in straight in.
export function FrontDeskPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [board, setBoard] = useState(null);
  const [error, setError] = useState("");
  const [booking, setBooking] = useState(params.get("book") ? { room: params.get("book") } : null);
  const today = isoDay(new Date());
  const date = params.get("date") || today;
  const load = useCallback(() => api(`/api/v1/hotel/rooms/?date=${date}`).then((data) => { setBoard(data); setError(""); }).catch((e) => setError(e.message)), [date]);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load, { pollMs: 60000 });
  const setDate = (value) => setParams(value && value !== today ? { date: value } : {});
  const clean = async (room) => {
    try { await api(`/api/v1/hotel/rooms/${room.id}/`, { method: "PATCH", body: JSON.stringify({ condition: "READY" }) }); void load(); }
    catch (e) { setError(e.message); }
  };

  if (error && !board) return <ErrorState message={error} retry={load} />;
  if (!board) return <Loading />;
  const counts = board.counts;
  const manage = can(user, "hotel.add_room");
  return <div className="hotelPage">
    <header className="hotelHead">
      <div><span className="eyebrow">Rooms & guests</span><h1>Front desk</h1>
        <p className="muted">{date === today ? "Today" : day(date)}: {counts.OCCUPIED} in, {counts.arrivals} arriving, {counts.departures} leaving, {counts.FREE} free{counts.to_clean ? `, ${counts.to_clean} to clean` : ""}.</p></div>
      <div className="actionRow">
        <label>Date<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        {can(user, "hotel.add_stay") && <button type="button" onClick={() => setBooking({})}><UserPlus size={16} aria-hidden="true" /> Book or check in</button>}
        <Link className="button secondary" to="/admin/rooms/guests">Guests & bookings</Link>
        {manage && <Link className="button secondary" to="/admin/rooms/setup"><Settings2 size={16} aria-hidden="true" /> Rooms & prices</Link>}
      </div>
    </header>
    {error && <FormError title="Something did not work." message={error} />}
    {booking && <BookingForm rooms={board.rooms} start={booking} date={date} onDone={(stay) => { setBooking(null); if (stay) navigate(`/admin/rooms/stays/${stay.id}`); }} />}
    {board.rooms.length === 0 ? <Empty>
      <BedDouble size={28} aria-hidden="true" />
      <b>No rooms yet</b>
      <span>{manage ? "Add your rooms and what each kind costs a night." : "Ask the owner to add the rooms."}</span>
      {manage && <Link className="button" to="/admin/rooms/setup">Add rooms</Link>}
    </Empty> : <ul className="roomBoard" aria-label="Rooms">
      {board.rooms.map((room) => <li key={room.id}><RoomCard room={room} user={user} onBook={() => setBooking({ room: String(room.id) })} onClean={() => void clean(room)} /></li>)}
    </ul>}
  </div>;
}

function RoomCard({ room, user, onBook, onClean }) {
  const stay = room.stay;
  return <article className={`roomCard ${room.state}`} aria-label={`Room ${room.number}`}>
    <header><strong>{room.number}</strong><span className="roomState">{ROOM_STATES[room.state]}</span></header>
    <small>{room.type} · {money(room.rate)} a night</small>
    {stay && <Link to={`/admin/rooms/stays/${stay.id}`} className="roomGuest">{stay.guest}</Link>}
    {stay && <small>{day(stay.arrival)} → {day(stay.departure)}{room.leaving ? " · leaving today" : ""}</small>}
    {room.arriving && <small>Arriving: <Link to={`/admin/rooms/stays/${room.arriving.id}`}>{room.arriving.guest}</Link></small>}
    {room.condition !== "READY" && room.state !== "OUT_OF_ORDER" && <span className={`roomFlag${room.condition === "DIRTY" ? " dirty" : ""}`}>{CONDITIONS[room.condition]}</span>}
    {room.note && <small>{room.note}</small>}
    <div className="actionRow">
      {room.state === "FREE" && can(user, "hotel.add_stay") && <button type="button" onClick={onBook}>Book</button>}
      {stay?.status === "BOOKED" && <Link className="button" to={`/admin/rooms/stays/${stay.id}`}>Check in</Link>}
      {room.condition === "DIRTY" && can(user, "hotel.change_stay") && <button type="button" className="secondary" onClick={onClean}>Cleaned</button>}
    </div>
  </article>;
}

// A booking, or a walk-in checked in now. A returning guest is found by their phone number.
function BookingForm({ rooms, start, date, onDone }) {
  const today = isoDay(new Date());
  const [form, setForm] = useState({ room: start.room || "", arrival: date, departure: addDays(date, 1), guest_name: "", phone: "", id_number: "",
    guests: 1, rate: "", paid: "", method: "CASH", reference: "", note: "", check_in_now: date === today });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (changes) => setForm((current) => ({ ...current, ...changes }));
  const room = rooms.find((r) => String(r.id) === String(form.room));
  const nights = nightsBetween(form.check_in_now ? today : form.arrival, form.departure);
  const rate = form.rate !== "" ? Number(form.rate) : Number(room?.rate || 0);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const body = { ...form, guests: Number(form.guests) || 1, ...(form.check_in_now ? { arrival: undefined } : {}) };
      if (body.rate === "") delete body.rate;
      if (!body.paid) { delete body.paid; delete body.method; delete body.reference; }
      onDone(await api("/api/v1/hotel/stays/", { method: "POST", body: JSON.stringify(body) }));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <form className="hotelForm" onSubmit={(e) => void submit(e)} aria-label="Book a room">
    <h2>{form.check_in_now ? "Check a guest in" : "Book a room"}</h2>
    <fieldset disabled={busy} className="chamaPlainFieldset">
      <div className="formGrid">
        <label>Room<select required value={form.room} onChange={(e) => set({ room: e.target.value })}>
          <option value="">Choose a room</option>
          {rooms.filter((r) => r.state !== "OUT_OF_ORDER").map((r) => <option key={r.id} value={r.id}>{r.number} · {r.type} · {money(r.rate)}{r.state !== "FREE" ? ` (${ROOM_STATES[r.state].toLowerCase()})` : ""}</option>)}
        </select></label>
        <label className="checkLine"><input type="checkbox" checked={form.check_in_now} onChange={(e) => set({ check_in_now: e.target.checked, arrival: e.target.checked ? today : form.arrival })} /> The guest is here now: check them in</label>
        {!form.check_in_now && <label>Arriving<input type="date" required min={today} value={form.arrival} onChange={(e) => set({ arrival: e.target.value, departure: e.target.value >= form.departure ? addDays(e.target.value, 1) : form.departure })} /></label>}
        <label>Leaving<input type="date" required min={addDays(form.check_in_now ? today : form.arrival, 1)} value={form.departure} onChange={(e) => set({ departure: e.target.value })} /></label>
        <label>Guest's name<TextBox required value={form.guest_name} onChange={(e) => set({ guest_name: e.target.value })} maxLength={160} /></label>
        <label>Phone<TextBox value={form.phone} onChange={(e) => set({ phone: e.target.value })} inputMode="tel" maxLength={30} placeholder="0712 345 678" /></label>
        <label>ID or passport number<TextBox value={form.id_number} onChange={(e) => set({ id_number: e.target.value })} maxLength={40} /></label>
        <label>Guests<input type="number" min="1" max="40" value={form.guests} onChange={(e) => set({ guests: e.target.value })} /></label>
        <label>Price a night<input type="number" min="0" step="0.01" inputMode="decimal" value={form.rate} placeholder={room ? String(Number(room.rate)) : ""} onChange={(e) => set({ rate: e.target.value })} /></label>
        <label>Paid now (optional)<input type="number" min="0" step="0.01" inputMode="decimal" value={form.paid} onChange={(e) => set({ paid: e.target.value })} /></label>
        {form.paid && <label>Paid by<select value={form.method} onChange={(e) => set({ method: e.target.value })}>{METHODS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>}
        {form.paid && form.method !== "CASH" && <label>{form.method === "MPESA" ? "M-Pesa code" : "Bank reference"}<TextBox required value={form.reference} onChange={(e) => set({ reference: e.target.value })} maxLength={100} /></label>}
        <label className="wide">Note (optional)<TextBox value={form.note} onChange={(e) => set({ note: e.target.value })} maxLength={255} placeholder="e.g. late arrival, company paying" /></label>
      </div>
    </fieldset>
    {room && nights > 0 && <p className="muted">{nights} {nights === 1 ? "night" : "nights"} at {money(rate)}: about {money(nights * rate)}. Each night is charged as it is stayed, so a guest who leaves early pays only the nights they stayed.</p>}
    <FormError title="Could not book the room." message={error} />
    <div className="actionRow">
      <button disabled={busy}>{busy ? "Saving…" : form.check_in_now ? "Check in" : "Book"}</button>
      <button type="button" className="secondary" onClick={() => onDone(null)}>Cancel</button>
    </div>
  </form>;
}

// Every booking and stay, found by guest, phone, room or number.
export function GuestsPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("BOOKED,IN");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api(`/api/v1/hotel/stays/?status=${status}&q=${encodeURIComponent(query)}`).then(setRows).catch((e) => setError(e.message)), [status, query]);
  useEffect(() => { const timer = setTimeout(() => void load(), 250); return () => clearTimeout(timer); }, [load]);
  useLiveRefresh(load);
  if (error && !rows) return <ErrorState message={error} retry={load} />;
  return <div className="hotelPage">
    <header className="hotelHead"><div><span className="eyebrow">Rooms & guests</span><h1>Guests & bookings</h1></div></header>
    <div className="hotelTabs" role="tablist" aria-label="Which stays">
      {[["BOOKED,IN", "Booked and in"], ["BOOKED", "Booked"], ["IN", "In now"], ["OUT", "Left"], ["CANCELLED,NO_SHOW", "Cancelled"], ["", "All"]].map(([id, name]) =>
        <button type="button" role="tab" key={id} aria-selected={status === id} className={status === id ? "" : "secondary"} onClick={() => setStatus(id)}>{name}</button>)}
    </div>
    <label>Find a guest<TextBox value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name, phone, room or ID number" /></label>
    {!rows ? <Loading /> : rows.length === 0 ? <Empty>No stays match.</Empty> : <ul className="hotelList">
      {rows.map((stay) => <li key={stay.id}>
        <div><Link to={`/admin/rooms/stays/${stay.id}`}><b>{stay.guest}</b></Link>
          <small className="muted">Room {stay.room.number} · {day(stay.arrival)} → {day(stay.departure)} · {stay.status_label}{stay.phone ? ` · ${stay.phone}` : ""}</small></div>
        <Link className="button secondary" to={`/admin/rooms/stays/${stay.id}`}>Open</Link>
      </li>)}
    </ul>}
  </div>;
}
