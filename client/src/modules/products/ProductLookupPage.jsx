import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BackLink } from "../../components/navigation/BackLink";
import { ErrorState, Loading } from "../../components/States";
import { api } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";
import { ProductSearch } from "../storefront/components/ProductSearch";
import { useLiveRefresh } from "../../core/data/liveRefresh";

export function ProductLookupPage() {
  const [params, setParams] = useSearchParams();
  const productId = params.get("product"), variantId = params.get("variant");
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useLiveRefresh(() => setReload((x) => x + 1));
  useEffect(() => {
    if (!productId) return;
    let active = true;
    const load = () => api(`/api/v1/catalog/products/${encodeURIComponent(productId)}/`)
      .then(product => { if (active) { setDetail({ product, updated: new Date() }); setError(""); } })
      .catch(err => { if (active) setError(err.message); });
    void load();
    const refresh = () => { if (!document.hidden) void load(); };
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener("focus", refresh);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [productId, reload]);
  const product = String(detail?.product.id) === productId ? detail.product : null;
  const variant = product?.variants.find(row => String(row.id) === variantId);
  const location = product?.locations.find(row => String(row.variant_id) === variantId);
  const money = value => value == null ? "Not available" : `${businessCurrency()} ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
  return <section className="productLookup">
    <header><BackLink /><span className="eyebrow">Quick stock enquiry</span><h1>Product Lookup</h1><p>Search a name, item code or barcode to check a product’s price, available stock and shelf location.</p></header>
    <ProductSearch endpoint="/api/v1/catalog/products/search-suggestions/" exactScan minLength={1} limit={30}
      placeholder="Enter a product name or scan a barcode…"
      onSelect={row => { setError(""); setParams({ product: row.product_id, variant: row.id }, { replace: true }); }}
      renderResult={row => <span className="productSearchDetails"><strong>{row.product_name} — {row.variant_name}</strong><span>{row.category_name} · {row.sku}</span>{row.product_type !== "SERVICE" && <span>{Number(row.available)} in stock</span>}</span>} />
    {!productId && <div className="state">Search above and choose a result to see its stock and location.</div>}
    {error && <ErrorState message={error} retry={() => setReload(value => value + 1)} />}
    {productId && !product && !error && <Loading />}
    {product && !variant && <p role="status">This item is no longer available. Search for another product.</p>}
    {variant && <article className="panel lookupResult">
      <div className="heading"><div><span className="eyebrow">{product.category_name}</span><h2>{product.name} — {variant.name}</h2><p>SKU {variant.sku}{variant.barcode ? ` · Barcode ${variant.barcode}` : ""}</p></div><button type="button" className="secondary" onClick={() => setReload(value => value + 1)}>Refresh stock</button></div>
      {product.description && <p>{product.description}</p>}
      <p className="muted">{error ? "Updates unavailable. Last successful check: " : "Last checked: "}{detail.updated.toLocaleTimeString()} · Refreshes every 15 seconds</p>
      <div className="metrics"><article><span>Selling price</span><strong>{money(variant.selling_price)}</strong></article>{variant.latest_bp != null && <article><span>Latest buying price</span><strong>{money(variant.latest_bp)}</strong></article>}
        {product.product_type !== "SERVICE" && [["Available", variant.available], ["Physical stock", variant.physical], ["Reserved", variant.reserved]].map(([label, value]) => <article key={label}><span>{label}</span><strong>{value ?? "Not available"}</strong></article>)}
      </div>
      {product.product_type === "SERVICE" ? <p>Service — no physical stock or shelf required.</p> : <section><h3>Where to find it</h3>
        {location?.preferred_shelf && <p>Preferred shelf: {location.preferred_shelf.display_name} ({location.preferred_shelf.code})</p>}
        {location?.actual?.length ? <ul className="lookupLocations">{location.actual.map(shelf => <li key={shelf.shelf_id}><strong>{shelf.shelf__zone__name} → {shelf.shelf__code}</strong><span>{shelf.shelf__display_name}{shelf.shelf__level__stack__display_name ? ` · ${shelf.shelf__level__stack__display_name}` : ""}{shelf.shelf__level__level_number != null ? ` · Level ${shelf.shelf__level__level_number}` : ""}</span><span>{shelf.available} available · {shelf.reserved} reserved</span></li>)}</ul> : <p>No physical stock is recorded on a shelf.</p>}
      </section>}
      <Link className="textLink" to="/admin/products">Open in catalog management →</Link>
    </article>}
  </section>;
}
