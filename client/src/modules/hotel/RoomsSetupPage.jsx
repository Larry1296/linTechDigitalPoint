import { useCallback, useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";
import { can, CONDITIONS, money } from "./shared";
import "./hotel.css";

// The hotel's kinds of room and their price a night, its rooms, and the check-out time after which another night is due.
export function RoomsSetupPage() {
  const { user } = useAuth();
  const [types, setTypes] = useState(null);
  const [board, setBoard] = useState(null);
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => Promise.all([api("/api/v1/hotel/room-types/"), api("/api/v1/hotel/rooms/"), api("/api/v1/hotel/settings/")])
    .then(([t, b, s]) => { setTypes(t); setBoard(b); setSettings(s); setError(""); }).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  if (error && !types) return <ErrorState message={error} retry={load} />;
  if (!types || !board || !settings) return <Loading />;
  const manage = can(user, "hotel.change_room");
  const run = async (task) => { setError(""); try { await task(); await load(); } catch (e) { setError(e.message); } };
  return <div className="hotelPage">
    <header className="hotelHead"><div><span className="eyebrow">Rooms & guests</span><h1>Rooms & prices</h1>
      <p className="muted">Each kind of room has its price a night; a guest's price can still be agreed when booking.</p></div></header>
    {error && <FormError title="Could not save." message={error} />}

    <h2>Kinds of room</h2>
    <ul className="hotelList">{types.map((type) => <TypeRow key={type.id} type={type} manage={manage} run={run} />)}</ul>
    {can(user, "hotel.add_roomtype") && <AddType run={run} />}

    <h2>Rooms</h2>
    {types.length === 0 ? <p className="muted">Add a kind of room first.</p> : <>
      <ul className="hotelList">{board.rooms.map((room) => <RoomRow key={room.id} room={room} types={types} manage={manage} run={run} />)}</ul>
      {can(user, "hotel.add_room") && <AddRoom types={types} run={run} />}
    </>}

    <h2>Check-out time</h2>
    <CheckoutTime value={settings.checkout_time} manage={manage} run={run} />
  </div>;
}

function TypeRow({ type, manage, run }) {
  const [edit, setEdit] = useState(null);
  if (edit) return <li><form className="hotelForm" onSubmit={(e) => { e.preventDefault(); void run(async () => {
    await api(`/api/v1/hotel/room-types/${type.id}/`, { method: "PATCH", body: JSON.stringify(edit) }); setEdit(null); }); }}>
    <div className="formGrid">
      <label>Name<TextBox required value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} maxLength={180} /></label>
      <label>Price a night<input type="number" min="0" step="0.01" required value={edit.rate} onChange={(e) => setEdit({ ...edit, rate: e.target.value })} /></label>
      <label>Sleeps<input type="number" min="1" max="20" value={edit.sleeps} onChange={(e) => setEdit({ ...edit, sleeps: e.target.value })} /></label>
    </div>
    <div className="actionRow"><button>Save</button><button type="button" className="secondary" onClick={() => setEdit(null)}>Cancel</button></div>
  </form></li>;
  return <li className={type.active ? "" : "off"}>
    <div><b>{type.name}</b><small className="muted">{money(type.rate)} a night · sleeps {type.sleeps} · {type.rooms} {type.rooms === 1 ? "room" : "rooms"}</small></div>
    {manage && <div className="actionRow"><button type="button" className="secondary" onClick={() => setEdit({ name: type.name, rate: String(Number(type.rate)), sleeps: type.sleeps })}>Change</button></div>}
  </li>;
}

function AddType({ run }) {
  const [form, setForm] = useState({ name: "", rate: "", sleeps: 2 });
  return <form className="hotelForm" aria-label="Add a kind of room" onSubmit={(e) => { e.preventDefault(); void run(async () => {
    await api("/api/v1/hotel/room-types/", { method: "POST", body: JSON.stringify(form) }); setForm({ name: "", rate: "", sleeps: 2 }); }); }}>
    <div className="formGrid">
      <label>Kind of room<TextBox required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={180} placeholder="Single, Double, Deluxe" /></label>
      <label>Price a night<input type="number" min="0" step="0.01" required value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} /></label>
      <label>Sleeps<input type="number" min="1" max="20" value={form.sleeps} onChange={(e) => setForm({ ...form, sleeps: e.target.value })} /></label>
    </div>
    <div className="actionRow"><button>Add kind of room</button></div>
  </form>;
}

function RoomRow({ room, types, manage, run }) {
  const save = (changes) => run(() => api(`/api/v1/hotel/rooms/${room.id}/`, { method: "PATCH", body: JSON.stringify(changes) }));
  return <li>
    <div><b>Room {room.number}</b><small className="muted">{room.type}{room.floor ? ` · ${room.floor}` : ""} · {CONDITIONS[room.condition]}</small></div>
    {manage && <div className="actionRow">
      <label><span className="sr">Kind of room {room.number}</span><select value={room.type_id} onChange={(e) => void save({ room_type: Number(e.target.value) })}>
        {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      <label><span className="sr">Condition of room {room.number}</span><select value={room.condition} onChange={(e) => void save({ condition: e.target.value })}>
        {Object.entries(CONDITIONS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
    </div>}
  </li>;
}

function AddRoom({ types, run }) {
  const [form, setForm] = useState({ number: "", room_type: String(types[0]?.id || ""), floor: "" });
  return <form className="hotelForm" aria-label="Add a room" onSubmit={(e) => { e.preventDefault(); void run(async () => {
    await api("/api/v1/hotel/rooms/", { method: "POST", body: JSON.stringify({ ...form, room_type: Number(form.room_type) }) }); setForm({ ...form, number: "" }); }); }}>
    <div className="formGrid">
      <label>Room number or name<TextBox required value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} maxLength={20} placeholder="101" /></label>
      <label>Kind of room<select value={form.room_type} onChange={(e) => setForm({ ...form, room_type: e.target.value })}>
        {types.filter((t) => t.active).map((t) => <option key={t.id} value={t.id}>{t.name} · {money(t.rate)}</option>)}</select></label>
      <label>Floor or wing (optional)<TextBox value={form.floor} onChange={(e) => setForm({ ...form, floor: e.target.value })} maxLength={40} /></label>
    </div>
    <div className="actionRow"><button>Add room</button></div>
  </form>;
}

function CheckoutTime({ value, manage, run }) {
  const [time, setTime] = useState(value);
  return <form className="hotelForm" onSubmit={(e) => { e.preventDefault(); void run(() => api("/api/v1/hotel/settings/", { method: "PATCH", body: JSON.stringify({ checkout_time: time }) })); }}>
    <p className="muted">A night is charged when the guest checks in, and another each time they are still in after this time.</p>
    <label>Guests leave by<input type="time" value={time} disabled={!manage} onChange={(e) => setTime(e.target.value)} /></label>
    {manage && <div className="actionRow"><button disabled={time === value}>Save</button></div>}
  </form>;
}
