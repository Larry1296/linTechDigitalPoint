import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";
import { can, day, isoDay, money } from "./shared";
import "./hotel.css";

// The menu: what the kitchen makes and its price. A dish sells at the till without any stock count; one that has run out
// today is marked so and leaves the till until it is back.
export function MenuPage() {
  const { user } = useAuth();
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", price: "", group: "" });
  const [editing, setEditing] = useState(null);
  const load = useCallback(() => api("/api/v1/hotel/menu/").then((data) => { setItems(data); setError(""); }).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load);
  if (error && !items) return <ErrorState message={error} retry={load} />;
  if (!items) return <Loading />;
  const manage = can(user, "hotel.change_menuitem");
  const save = async (id, changes) => {
    setError("");
    try { await api(`/api/v1/hotel/menu/${id}/`, { method: "PATCH", body: JSON.stringify(changes) }); setEditing(null); await load(); }
    catch (e) { setError(e.message); }
  };
  const add = async (event) => {
    event.preventDefault(); setError("");
    try { await api("/api/v1/hotel/menu/", { method: "POST", body: JSON.stringify({ ...form, group: form.group || "Menu" }) }); setForm({ name: "", price: "", group: form.group }); await load(); }
    catch (e) { setError(e.message); }
  };
  const groups = [...new Set(items.filter((i) => i.active).map((i) => i.group))];
  return <div className="hotelPage">
    <header className="hotelHead"><div><span className="eyebrow">Menu & kitchen</span><h1>Menu</h1>
      <p className="muted">Meals and drinks you make. They sell at the till without counting plates; what they cost is what the <Link to="/admin/kitchen">kitchen</Link> uses.</p></div></header>
    {error && <FormError title="Could not save." message={error} />}
    {items.length === 0 && <Empty>Nothing on the menu yet. Add your first dish below.</Empty>}
    {groups.map((group) => <section key={group}>
      <h2>{group}</h2>
      <ul className="hotelList">{items.filter((item) => item.active && item.group === group).map((item) => <li key={item.id} className={item.available ? "" : "off"}>
        {editing?.id === item.id ? <form className="hotelForm" onSubmit={(e) => { e.preventDefault(); void save(item.id, { name: editing.name, price: editing.price, group: editing.group }); }}>
          <div className="formGrid">
            <label>Name<TextBox required value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} maxLength={180} /></label>
            <label>Price<input type="number" min="0" step="0.01" required value={editing.price} onChange={(e) => setEditing({ ...editing, price: e.target.value })} /></label>
            <label>Heading<TextBox value={editing.group} onChange={(e) => setEditing({ ...editing, group: e.target.value })} maxLength={120} list="menu-groups" /></label>
          </div>
          <div className="actionRow"><button>Save</button><button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button>
            <button type="button" className="secondary" onClick={() => void save(item.id, { active: false })}>Take off the menu</button></div>
        </form> : <>
          <div><b>{item.name}</b><small className="muted">{money(item.price)}{item.available ? "" : " · run out today"}</small></div>
          <div className="actionRow">
            {can(user, "commerce.add_sale") && <button type="button" className="secondary" onClick={() => void save(item.id, { available: !item.available })}>{item.available ? "Run out" : "Back on"}</button>}
            {manage && <button type="button" className="secondary" onClick={() => setEditing({ id: item.id, name: item.name, price: String(Number(item.price)), group: item.group })}>Change</button>}
          </div>
        </>}
      </li>)}</ul>
    </section>)}
    <datalist id="menu-groups">{groups.map((group) => <option key={group} value={group} />)}</datalist>
    {can(user, "hotel.add_menuitem") && <form className="hotelForm" onSubmit={(e) => void add(e)} aria-label="Add to the menu">
      <h2>Add to the menu</h2>
      <div className="formGrid">
        <label>Dish or drink<TextBox required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={180} placeholder="Pilau, Tea, Fish fry" /></label>
        <label>Price<input type="number" min="0" step="0.01" required value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></label>
        <label>Heading<TextBox value={form.group} onChange={(e) => setForm({ ...form, group: e.target.value })} maxLength={120} list="menu-groups" placeholder="Breakfast, Meals, Drinks" /></label>
      </div>
      <div className="actionRow"><button>Add</button></div>
    </form>}
  </div>;
}

// The kitchen: the stock bought for cooking, and what it used. Enter what was used, or count what is left and the app
// works out what was used. Its cost, at what the stock cost to buy, is the cost of the meals sold.
export function KitchenPage() {
  const { user } = useAuth();
  const [ingredients, setIngredients] = useState(null);
  const [history, setHistory] = useState([]);
  const [way, setWay] = useState("COUNTED");
  const [amounts, setAmounts] = useState({});
  const [usedOn, setUsedOn] = useState(isoDay(new Date()));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState({ name: "", unit: "" });
  const load = useCallback(() => Promise.all([api("/api/v1/hotel/kitchen/ingredients/"), can(user, "hotel.view_kitchenuse") ? api("/api/v1/hotel/kitchen/use/") : []])
    .then(([rows, uses]) => { setIngredients(rows); setHistory(uses); setError(""); }).catch((e) => setError(e.message)), [user]);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load);
  if (error && !ingredients) return <ErrorState message={error} retry={load} />;
  if (!ingredients) return <Loading />;
  const record = async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    const key = way === "USED" ? "quantity" : "left";
    try {
      await api("/api/v1/hotel/kitchen/use/", { method: "POST", body: JSON.stringify({ way, used_on: usedOn,
        lines: Object.entries(amounts).filter(([, value]) => value !== "").map(([id, value]) => ({ ingredient_id: Number(id), [key]: value })) }) });
      setAmounts({}); await load();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const addIngredient = async (event) => {
    event.preventDefault(); setError("");
    try { await api("/api/v1/hotel/kitchen/ingredients/", { method: "POST", body: JSON.stringify(added) }); setAdded({ name: "", unit: "" }); await load(); }
    catch (e) { setError(e.message); }
  };
  const unit = (row) => row.unit ? ` ${row.unit}` : "";
  const stockValue = ingredients.reduce((sum, row) => sum + Number(row.value || 0), 0);
  return <div className="hotelPage">
    <header className="hotelHead"><div><span className="eyebrow">Menu & kitchen</span><h1>Kitchen</h1>
      <p className="muted">Stock bought for cooking comes in through <Link to="/admin/quick-receive">Receive stock</Link>. Record what the kitchen used each day: its cost is the cost of the meals sold.</p></div>
      {can(user, "accounting.view_profit") && <dl className="hotelFigures"><div><dt>Kitchen stock worth</dt><dd>{money(stockValue)}</dd></div></dl>}
    </header>
    {error && <FormError title="Could not save." message={error} />}
    {ingredients.length === 0 ? <Empty>No kitchen stock yet. Add what you cook with (flour, oil, sugar, meat) below, then receive it like any stock.</Empty>
      : can(user, "hotel.add_kitchenuse") && <form className="hotelForm" onSubmit={(e) => void record(e)} aria-label="What the kitchen used">
        <h2>What the kitchen used</h2>
        <div className="hotelTabs" role="tablist" aria-label="How">
          <button type="button" role="tab" aria-selected={way === "COUNTED"} className={way === "COUNTED" ? "" : "secondary"} onClick={() => { setWay("COUNTED"); setAmounts({}); }}>I counted what is left</button>
          <button type="button" role="tab" aria-selected={way === "USED"} className={way === "USED" ? "" : "secondary"} onClick={() => { setWay("USED"); setAmounts({}); }}>I know what was used</button>
        </div>
        <label>Day<input type="date" max={isoDay(new Date())} value={usedOn} onChange={(e) => setUsedOn(e.target.value)} /></label>
        <div className="tableWrap"><table className="kitchenRows">
          <thead><tr><th>Ingredient</th><th>In the store</th><th>{way === "USED" ? "Used" : "Left now"}</th>{way === "COUNTED" && <th>Used</th>}</tr></thead>
          <tbody>{ingredients.map((row) => {
            const value = amounts[row.id] ?? "";
            const used = way === "COUNTED" && value !== "" ? Number(row.in_store) - Number(value) : null;
            return <tr key={row.id}>
              <td>{row.name}</td>
              <td>{Number(row.in_store).toLocaleString()}{unit(row)}</td>
              <td><input type="number" min="0" step="any" inputMode="decimal" aria-label={`${row.name} ${way === "USED" ? "used" : "left"}`} value={value}
                onChange={(e) => setAmounts({ ...amounts, [row.id]: e.target.value })} /></td>
              {way === "COUNTED" && <td className={used !== null && used < 0 ? "formWarning" : ""}>{used === null ? "—" : `${used.toLocaleString()}${unit(row)}`}</td>}
            </tr>;
          })}</tbody>
        </table></div>
        <p className="muted">Leave an ingredient blank if it was not {way === "USED" ? "used" : "counted"}.</p>
        <div className="actionRow"><button disabled={busy || !Object.values(amounts).some((v) => v !== "")}>{busy ? "Saving…" : "Record kitchen use"}</button></div>
      </form>}

    {can(user, "hotel.add_kitcheningredient") && <form className="hotelForm" onSubmit={(e) => void addIngredient(e)} aria-label="Add kitchen stock">
      <h2>Add kitchen stock</h2>
      <div className="formGrid">
        <label>Ingredient<TextBox required value={added.name} onChange={(e) => setAdded({ ...added, name: e.target.value })} maxLength={180} placeholder="Wheat flour, Cooking oil" /></label>
        <label>Counted in<TextBox value={added.unit} onChange={(e) => setAdded({ ...added, unit: e.target.value })} maxLength={40} placeholder="kg, litre, packet" /></label>
      </div>
      <div className="actionRow"><button>Add</button></div>
    </form>}

    {history.length > 0 && <>
      <h2>Kitchen use</h2>
      <ul className="hotelList">{history.map((use) => <li key={use.id}>
        <div><b>{day(use.used_on)}</b><small className="muted">{use.lines.map((line) => `${line.name} ${Number(line.quantity).toLocaleString()}${line.unit ? ` ${line.unit}` : ""}`).join(", ")}</small></div>
        <b>{money(use.total_cost)}</b>
      </li>)}</ul>
    </>}
  </div>;
}
