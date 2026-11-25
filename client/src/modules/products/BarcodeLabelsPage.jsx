import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Printer } from "lucide-react";
import { api } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";
import { Empty, ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
import { Barcode } from "../../core/scanner/Barcode";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const named = (p) => (p.variant_name && p.variant_name !== "Standard" ? `${p.product_name} · ${p.variant_name}` : p.product_name);

// Labels to stick on products, so the camera or a scanner at the till finds each one. A product without the maker's
// barcode gets the shop's own when its labels are first printed; it never changes, so stuck labels keep working.
// The sheet is laid out three across on A4, the size of the common 21-label sheets (63.5 × 38.1 mm), and fits plain paper.
export function BarcodeLabelsPage() {
  const [rows, setRows] = useState();
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [missingOnly, setMissingOnly] = useState(true);
  const [copies, setCopies] = useState({});
  const [chosen, setChosen] = useState(() => new Set());
  const [printing, setPrinting] = useState();
  const [busy, setBusy] = useState(false);
  const [printError, setPrintError] = useState("");
  const load = () => api("/api/v1/commerce/pos/catalog/").then((data) => { setRows(data.filter((p) => p.product_type !== "SERVICE")); setError(""); })
    .catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []);
  const categories = useMemo(() => [...new Set((rows || []).map((p) => p.category_name).filter(Boolean))].sort(), [rows]);
  const words = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = (rows || []).filter((p) => (!missingOnly || !p.barcode) && (!category || p.category_name === category)
    && words.every((w) => `${named(p)} ${p.sku} ${p.barcode || ""}`.toLowerCase().includes(w)));
  const allShown = shown.length > 0 && shown.every((p) => chosen.has(p.id));
  const toggle = (id) => setChosen((old) => { const next = new Set(old); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const toggleAll = () => setChosen((old) => { const next = new Set(old); shown.forEach((p) => (allShown ? next.delete(p.id) : next.add(p.id))); return next; });
  const count = (id) => Math.max(1, Math.min(200, Number(copies[id]) || 1));
  const total = [...chosen].reduce((sum, id) => sum + count(id), 0);

  useEffect(() => {
    if (!printing) return undefined;
    const before = document.title;
    document.title = "Barcode labels";
    const done = () => { document.title = before; setPrinting(undefined); };
    window.addEventListener("afterprint", done, { once: true });
    const timer = setTimeout(() => window.print(), 50);
    return () => { clearTimeout(timer); window.removeEventListener("afterprint", done); document.title = before; };
  }, [printing]);

  const print = async () => {
    setBusy(true);
    setPrintError("");
    try {
      const ids = [...chosen];
      const { labels } = await api("/api/v1/catalog/barcodes/labels/", { method: "POST", body: JSON.stringify({ variant_ids: ids }) });
      setPrinting(labels.filter((l) => l.barcode).flatMap((l) => Array.from({ length: count(l.id) }, () => l)));
      await load();
    } catch (err) {
      setPrintError(err.message);
    } finally { setBusy(false); }
  };

  if (error) return <ErrorState message={error} retry={load} />;
  if (!rows) return <Loading />;
  const without = rows.filter((p) => !p.barcode).length;
  return (
    <div className="barcodeLabelsPage">
      <h1>Barcode labels</h1>
      <p className="muted">Stick a label on each product so the till finds it when its barcode is passed in front of the camera or a scanner.
        A product that already has the maker's barcode on its box needs no label: scan it once at the till and pick the product, and it is saved.
        Products without a barcode get the shop's own when you print their labels.</p>
      <p><strong>{without}</strong> of {rows.length} products have no barcode yet.</p>
      <div className="barcodeLabelsFilters">
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a product" aria-label="Find a product" />
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <label><input type="checkbox" checked={missingOnly} onChange={(e) => setMissingOnly(e.target.checked)} /> Only products without a barcode</label>
      </div>
      <div className="barcodeLabelsBar">
        <label><input type="checkbox" checked={allShown} onChange={toggleAll} disabled={!shown.length} /> Choose all shown ({shown.length})</label>
        <button type="button" disabled={!chosen.size || busy} onClick={() => void print()}>
          <Printer size={17} aria-hidden="true" /> {busy ? "Preparing…" : `Print ${total} label${total === 1 ? "" : "s"}`}</button>
      </div>
      <FormError title="Could not prepare the labels." message={printError} />
      {shown.length ? <ul className="barcodeLabelsList">{shown.map((p) => (
        <li key={p.id}>
          <label className="barcodeLabelsPick">
            <input type="checkbox" checked={chosen.has(p.id)} onChange={() => toggle(p.id)} />
            <span><b>{named(p)}</b><small className="muted">{p.barcode ? `Barcode ${p.barcode}` : "No barcode yet"} · {money(p.selling_price)}</small></span>
          </label>
          <label className="barcodeLabelsCopies">Labels
            <input type="number" min="1" max="200" value={copies[p.id] ?? 1} onChange={(e) => setCopies((old) => ({ ...old, [p.id]: e.target.value }))}
              aria-label={`Labels for ${named(p)}`} />
          </label>
        </li>
      ))}</ul> : <Empty>{missingOnly ? "Every product shown has a barcode." : "No products match."}</Empty>}
      {printing && createPortal(<div className="barcodeSheet" aria-hidden="true">
        {printing.map((l, i) => <div className="barcodeLabel" key={i}>
          <b>{named(l)}</b>
          <span>{money(l.selling_price)}</span>
          <Barcode code={l.barcode} />
        </div>)}
      </div>, document.body)}
    </div>
  );
}
