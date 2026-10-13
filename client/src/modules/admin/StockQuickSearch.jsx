import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { api } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";

// The counter's quick answer when a customer asks "do you have…?": type any words ("mobile charger", "micro usb",
// even with a typo) and every matching product shows at once with its price, how many are in stock and the shelf.
export function StockQuickSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const words = query.trim();
    if (!words) { setResults(null); setError(""); return undefined; }
    let live = true;
    const timer = setTimeout(() => {
      api(`/api/v1/catalog/products/search-suggestions/?q=${encodeURIComponent(words)}`)
        .then((rows) => { if (live) { setResults(rows.filter((row) => row.product_type !== "SERVICE")); setError(""); } })
        .catch((err) => { if (live) setError(err.message); });
    }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [query]);
  const price = (value) => `${businessCurrency()} ${Number(value).toLocaleString()}`;
  // What is on the shelves first, so the answer to the customer is at the top.
  const rows = [...(results || [])].sort((a, b) => (Number(b.available) > 0) - (Number(a.available) > 0));
  const inStock = rows.filter((row) => Number(row.available) > 0).length;
  return <section className="stockQuickSearch" aria-labelledby="stock-search-title">
    <h2 id="stock-search-title">Do we have it?</h2>
    <div className="stockQuickSearchBox">
      <Search size={18} aria-hidden="true" />
      <input type="search" value={query} onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Escape") setQuery(""); }}
        placeholder="Type what the customer wants, e.g. mobile charger" aria-label="Search stock" autoComplete="off" />
      {query && <button type="button" className="secondary" onClick={() => setQuery("")} aria-label="Clear search"><X size={16} aria-hidden="true" /></button>}
    </div>
    {error && <p className="formNotice" role="alert">Could not search right now: {error}</p>}
    {results && !error && <p className="muted" role="status">{rows.length
      ? `${rows.length} ${rows.length === 1 ? "product" : "products"} found · ${inStock} in stock`
      : "Nothing matches. Try another word, such as the brand or what it is used for."}</p>}
    {rows.length > 0 && <ul className="stockQuickResults">
      {rows.map((row) => {
        const count = Number(row.available);
        const shelves = row.locations.map((place) => place.shelf_name || place.shelf_code).filter(Boolean);
        return <li key={row.id} className={count > 0 ? undefined : "out"}>
          <a href={`/admin/product-lookup?product=${row.product_id}&variant=${row.id}`}>
            <strong>{row.product_name}{row.variant_name && row.variant_name !== "Standard" ? ` — ${row.variant_name}` : ""}</strong>
            <span className="muted">{row.category_name}{shelves.length ? ` · ${[...new Set(shelves)].join(", ")}` : ""}</span>
          </a>
          <span className="stockQuickPrice">{price(row.selling_price)}</span>
          <span className="stockQuickCount">{count > 0 ? `${count.toLocaleString()} in stock` : "Out of stock"}</span>
        </li>;
      })}
    </ul>}
  </section>;
}
