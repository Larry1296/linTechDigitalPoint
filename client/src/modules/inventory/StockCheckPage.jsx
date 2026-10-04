import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { confirmAction } from "../../core/ui/alerts";
import { ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const qty = (value) => Number(value || 0).toLocaleString();
const SAVED = "stock-check-counts";

// Counts typed so far survive a reload on this device, so a long count is not lost.
function loadCounts() {
  try { return JSON.parse(localStorage.getItem(SAVED) || "{}"); } catch { return {}; }
}
function saveCounts(counts) {
  try { localStorage.setItem(SAVED, JSON.stringify(counts)); } catch { /* private window: counts stay in memory */ }
}

// One product counted short or over: record what happened to the difference.
function Settle({ row, counted, canSell, onDone }) {
  const missing = Number(row.on_shelf) - counted;
  const [kind, setKind] = useState(missing > 0 ? "sold" : "found");
  const [price, setPrice] = useState(String(Number(row.selling_price)));
  const [method, setMethod] = useState("CASH");
  const [cost, setCost] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const units = Math.abs(missing);
  const submit = async (event) => {
    event.preventDefault();
    const text = kind === "sold" ? `Record ${qty(units)} × ${row.name} as sold at ${money(price)} each (${money(units * Number(price))}, paid by ${method === "MPESA" ? "Lipa na M-Pesa" : "cash"})?`
      : kind === "found" ? `Add ${qty(units)} × ${row.name} to your stock? It was already yours, so it does not count as profit.`
      : `Record ${qty(units)} × ${row.name} as ${kind}? Its buying price counts as a loss.`;
    if (!(await confirmAction({ title: "Record this difference?", text, confirmButtonText: "Record" }))) return;
    setBusy(true);
    setError("");
    try {
      if (kind === "sold") {
        await api("/api/v1/commerce/pos/complete/", { method: "POST", body: JSON.stringify({
          items: [{ variant_id: row.id, quantity: units, ...(Number(price) !== Number(row.selling_price) ? { unit_price: price } : {}) }],
          payment_method: method, idempotency_key: crypto.randomUUID() }) });
      } else {
        await api("/api/v1/inventory/stock-check/", { method: "POST", body: JSON.stringify({
          variant_id: row.id, quantity: units, kind, note: "Stock check", ...(kind === "found" && cost ? { unit_cost: cost } : {}) }) });
      }
      await onDone();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="stockSettle" onSubmit={(event) => void submit(event)}>
      <p><b>{row.name}</b>: {missing > 0 ? `${qty(units)} missing` : `${qty(units)} extra`} (the app has {qty(row.on_shelf)}, you counted {qty(counted)})</p>
      <fieldset disabled={busy}>
        <label>What happened?
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            {missing > 0 ? <>
              {canSell && <option value="sold">Sold, but not recorded</option>}
              <option value="lost">Lost or stolen</option>
              <option value="damaged">Damaged, thrown away</option>
            </> : <option value="found">Already mine, not entered</option>}
          </select>
        </label>
        {kind === "sold" && <>
          <label>Price each ({businessCurrency()})<input type="number" min="0" step="0.01" required value={price} onChange={(event) => setPrice(event.target.value)} /></label>
          <label>Paid by<select value={method} onChange={(event) => setMethod(event.target.value)}><option value="CASH">Cash</option><option value="MPESA">Lipa na M-Pesa (till)</option></select></label>
        </>}
        {kind === "found" && row.buying_price == null && <label>Buying price each ({businessCurrency()})<input type="number" min="0.01" step="0.01" required value={cost} onChange={(event) => setCost(event.target.value)} /></label>}
        <button>Record</button>
      </fieldset>
      {kind === "sold" && method === "MPESA" && <p className="muted">A Lipa na M-Pesa sale waits for its code: confirm it in Sales History afterwards.</p>}
      <FormError title="Could not record it." message={error} />
    </form>
  );
}

export function StockCheckPage() {
  const { user } = useAuth();
  const canSell = Boolean(user?.permissions?.includes("commerce.add_sale"));
  const [rows, setRows] = useState();
  const [counts, setCounts] = useState(loadCounts);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const load = async () => {
    try {
      setRows(await api("/api/v1/inventory/stock-check/"));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => { void load(); }, []);
  useLiveRefresh(load);
  const setCount = (id, value) => setCounts((old) => { const next = { ...old, [id]: value }; saveCounts(next); return next; });
  const counted = (row) => (counts[row.id] === undefined || counts[row.id] === "" ? null : Number(counts[row.id]));
  const summary = useMemo(() => {
    const result = { counted: 0, missing: 0, extra: 0, atSelling: 0, atLowest: 0, atCost: 0, costKnown: true };
    for (const row of rows || []) {
      const count = counted(row);
      if (count == null) continue;
      result.counted += 1;
      const missing = Number(row.on_shelf) - count;
      if (missing > 0) {
        result.missing += missing;
        result.atSelling += missing * Number(row.selling_price);
        result.atLowest += missing * Number(row.lowest_price || row.selling_price);
        if (row.buying_price == null) result.costKnown = false; else result.atCost += missing * Number(row.buying_price);
      } else if (missing < 0) result.extra += -missing;
    }
    return result;
  }, [rows, counts]);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!rows) return <Loading />;
  const shown = rows.filter((row) => !filter || `${row.name} ${row.sku}`.toLowerCase().includes(filter.toLowerCase()));
  const differing = rows.filter((row) => counted(row) != null && counted(row) !== Number(row.on_shelf));
  const showCost = rows.some((row) => "buying_price" in row);
  return (
    <>
      <h1>Stock check</h1>
      <p className="muted">Count what is on your shelves and type it in. The app shows what is missing or extra and what it is worth.
        Then say what happened to each difference: <b>sold</b> items become sales (money and profit come in), <b>lost or damaged</b> items are a loss,
        and <b>extra</b> items are added to your stock.</p>
      <div className="stockCheckSummary" role="status">
        <article><span>Products counted</span><strong>{summary.counted} of {rows.length}</strong></article>
        <article><span>Items missing</span><strong>{qty(summary.missing)}</strong></article>
        <article><span>Worth at selling price</span><strong>{money(summary.atSelling)}</strong></article>
        <article><span>Worth at your lowest price</span><strong>{money(summary.atLowest)}</strong></article>
        {showCost && <article><span>What they cost you</span><strong>{summary.costKnown ? money(summary.atCost) : "Some buying prices missing"}</strong></article>}
        <article><span>Items extra</span><strong>{qty(summary.extra)}</strong></article>
      </div>
      {summary.missing > 0 && <p>If the missing items were sold, you should have between <b>{money(summary.atLowest)}</b> and <b>{money(summary.atSelling)}</b> for them
        (depending on bargaining). <Link to="/admin/money-check">Compare with the money you have</Link>.</p>}
      <label className="stockCheckFilter">Find a product<input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Name or code" /></label>
      <div className="trendTable"><table className="stockCheckTable">
        <thead><tr><th scope="col">Product</th><th scope="col">In the app</th><th scope="col">You counted</th><th scope="col">Difference</th>
          {showCost && <th scope="col">Buying price</th>}<th scope="col">Selling price</th></tr></thead>
        <tbody>{shown.map((row) => {
          const count = counted(row);
          const difference = count == null ? null : count - Number(row.on_shelf);
          return <tr key={row.id} className={difference ? "stockCheckOff" : undefined}>
            <th scope="row">{row.name}{row.variant && row.variant !== "Standard" ? ` — ${row.variant}` : ""}<br /><small className="muted">{row.sku}</small></th>
            <td>{qty(row.on_shelf)}</td>
            <td><input type="number" min="0" step="1" inputMode="numeric" aria-label={`Counted ${row.name}`} value={counts[row.id] ?? ""}
              onChange={(event) => setCount(row.id, event.target.value)} placeholder="—" /></td>
            <td>{difference == null ? "—" : difference === 0 ? "Matches" : difference < 0 ? `${qty(-difference)} missing` : `${qty(difference)} extra`}</td>
            {showCost && <td>{row.buying_price == null ? "—" : money(row.buying_price)}</td>}
            <td>{money(row.selling_price)}</td>
          </tr>;
        })}</tbody>
      </table></div>
      {differing.length > 0 && <section aria-labelledby="settle-heading">
        <h2 id="settle-heading">Differences to record ({differing.length})</h2>
        {differing.map((row) => <Settle key={`${row.id}-${row.on_shelf}`} row={row} counted={counted(row)} canSell={canSell} onDone={load} />)}
      </section>}
      {Object.keys(counts).length > 0 && <button type="button" className="secondary" onClick={() => { setCounts({}); saveCounts({}); }}>Clear my counts</button>}
    </>
  );
}
