import { BackLink } from "../../components/navigation/BackLink";
import { businessCurrency } from "../../core/organization/presentation";
import { ProductSearch } from "../storefront/components/ProductSearch";
import { ProductEditor } from "./ProductEditor";
import { categoryDefaults } from "./productDefaults";
import { VariantSummary, hasPermission } from "./VariantSummary";
import { useAuth } from "../../core/auth/AuthContext";
import { loadZonesIfUsed } from "../digital-shop/api";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ProductImage } from "../storefront/components/ProductImage";
import { Empty, ErrorState, Loading } from "../../components/States";
import { api } from "../../core/api/client";
import { ProductForm } from "./ProductForm";
import { ProductImport, downloadTemplate } from "./ProductImport";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { FileSpreadsheet, Trash2 } from "lucide-react";
import { DeleteProductsDialog, ProductSelection, useProductSelection } from "./DeleteProducts";
const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;
const count = (value) => Number(value || 0).toLocaleString();

// All the stock held now: goes up when stock is received and down when it is sold, used or lost (the page refreshes
// itself). What it cost shows only to those who may see buying prices; otherwise it is valued at selling price.
function StockTotals({ stock }) {
  if (!stock) return null;
  const showCost = "value_at_cost" in stock;
  return (
    <section className="stockTotals" aria-label="Stock you hold now">
      <dl className="factTiles">
        <div><dt>Items in stock</dt><dd>{count(stock.units)}</dd><small>{count(stock.products)} products</small></div>
        {showCost && <div><dt>Stock total at buying price (BP)</dt><dd>{money(stock.value_at_cost)}</dd>
          {stock.cost_missing > 0 && <small>{count(stock.cost_missing)} {stock.cost_missing === 1 ? "delivery has" : "deliveries have"} no buying price yet</small>}</div>}
        <div><dt>Stock total at selling price (SP)</dt><dd>{money(stock.value_at_selling_price)}</dd></div>
        {showCost && <div><dt>Profit if it all sells</dt><dd>{money(Number(stock.value_at_selling_price) - Number(stock.value_at_cost))}</dd></div>}
      </dl>
    </section>
  );
}

// A stock item with any variant at or below its restock level.
const needsRestock = (product) => product.product_type !== "SERVICE"
  && product.variants.some((v) => Number(v.available || 0) <= Number(v.minimum_stock || 0));

// One line per product on the shared list: what it is, what it sells for and how much is left.
function ProductRow({ product }) {
  const service = product.product_type === "SERVICE";
  const prices = product.variants.map((v) => Number(v.selling_price));
  const low = Math.min(...prices), high = Math.max(...prices);
  const available = product.variants.reduce((sum, v) => sum + Number(v.available || 0), 0);
  const restock = needsRestock(product);
  const selection = useProductSelection();
  return (
    <li className={selection?.mode ? `productRowSelectable deleting-${selection.mode}` : undefined}>
      {selection?.mode === "many" && <input type="checkbox" className="productPick" aria-label={`Select ${product.name}`}
        checked={selection.selected.has(product.id)} onChange={() => selection.toggle(product.id)} />}
      <Link className="productRow" to={`?product=${product.id}`}>
        <ProductImage product={{ images: product.variants[0]?.images, product_name: product.name }} />
        <span className="productRowMain">
          <strong>{product.name}</strong>
          <small>{[product.brand_name, product.variants.length > 1 ? `${product.variants.length} types` : product.variants[0]?.sku].filter(Boolean).join(" · ")}</small>
        </span>
        <span className="productRowPrice">{!prices.length ? "—" : low === high ? money(low) : `${money(low)} – ${Number(high).toLocaleString()}`}</span>
        <span className="productRowStock">
          {service ? <span className="stockBadge">Service</span>
            : <span className={`stockBadge${restock ? " low" : ""}`}>{count(available)} in stock{restock ? " · restock" : ""}</span>}
          {!product.active && <span className="stockBadge muted">Hidden</span>}
        </span>
        <span className="productRowChevron" aria-hidden="true">›</span>
      </Link>
      {selection?.mode === "one" && <button type="button" className="danger productDelete" aria-label={`Delete ${product.name}`}
        onClick={() => selection.askDelete([product.id])}><Trash2 size={16} aria-hidden="true" /> Delete</button>}
    </li>
  );
}

// The category tree is a flat list of paths; a category's children are the ones one level below it.
const samePath = (a, b) => a.length === b.length && a.every((part, index) => part === b[index]);
const childrenOf = (categories, path) => categories.filter((c) => c.path.length === path.length + 1 && samePath(c.path.slice(0, path.length), path));
// Products filed in a category and in everything below it.
const totalIn = (categories, counts, category) => categories
  .filter((c) => samePath(c.path.slice(0, category.path.length), category.path))
  .reduce((sum, c) => sum + Number(counts.categories?.[c.id] || 0), 0);

// One tile per category: its name, how many products are in it and below it, and how many sub-categories it has.
function CategoryCards({ categories, counts, items, other }) {
  if (!items.length && !other) return null;
  return <ul className="categoryCards" aria-label="Categories">
    {items.map((category) => {
      const total = totalIn(categories, counts, category);
      const below = childrenOf(categories, category.path).length;
      return <li key={category.id}><Link className={`categoryCard${total ? "" : " empty"}`} to={`?category=${category.id}`}>
        <strong>{category.path.at(-1)}</strong>
        <small>{[total ? `${count(total)} product${total === 1 ? "" : "s"}` : "No products yet",
          below ? `${below} sub-categor${below === 1 ? "y" : "ies"}` : ""].filter(Boolean).join(" · ")}</small>
        <span className="productRowChevron" aria-hidden="true">›</span>
      </Link></li>;
    })}
    {other > 0 && <li><Link className="categoryCard" to="?category=other">
      <strong>Other</strong><small>{count(other)} product{other === 1 ? "" : "s"} in hidden categories</small>
      <span className="productRowChevron" aria-hidden="true">›</span>
    </Link></li>}
  </ul>;
}

// "All products › Mobile Accessories › Wall Chargers", each step leading back up the tree.
function CategoryCrumbs({ categories, path, linkLast = false }) {
  return <nav className="productCrumbs" aria-label="Category">
    <Link to="?">All products</Link>
    {path.map((name, index) => {
      const step = categories.find((c) => samePath(c.path, path.slice(0, index + 1)));
      return <span key={index}> › {step && (linkLast || index < path.length - 1) ? <Link to={`?category=${step.id}`}>{name}</Link> : name}</span>;
    })}
  </nav>;
}

// The products filed directly in the open category.
function ProductTable({ rows }) {
  const deleteMode = useProductSelection()?.mode;
  return <div className="productGroups">
    <div className={`catalogHeader${deleteMode ? ` deleting-${deleteMode}` : ""}`} aria-hidden="true"><span>Product</span><span>Price</span><span>Stock</span></div>
    <ul className="productList catalogList">{rows.map((product) => <ProductRow key={product.id} product={product} />)}</ul>
  </div>;
}

// Items to restock get their own section on top; hidden products stay in the main list.
function RestockFirst({ rows }) {
  const restock = rows.filter((product) => product.active && needsRestock(product));
  const others = rows.filter((product) => !restock.includes(product));
  return <>
    {restock.length > 0 && <section className="restockSection" aria-labelledby="restock-heading">
      <h2 id="restock-heading">Needs restocking ({restock.length})</h2>
      <p className="muted">At or below their restock level. Receive stock to clear them from this list.</p>
      <ul className="productList catalogList">{restock.map((product) => <ProductRow key={product.id} product={product} />)}</ul>
    </section>}
    {others.length > 0 && <ProductTable rows={others} />}
  </>;
}

// Stock that arrived without a shelf (imports, opening stock) sits in the virtual "Unplaced stock" location.
const UNPLACED = "__UNPLACED__";

// Moves unplaced stock onto a real compartment, keeping its lot and cost.
function PlaceOnShelf({ variant, unplaced, zones, onPlaced }) {
  const [open, setOpen] = useState(false);
  const [shelf, setShelf] = useState("");
  const [quantity, setQuantity] = useState(String(Number(unplaced.available)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open) return <button type="button" className="secondary" onClick={() => setOpen(true)}>Place on a shelf</button>;
  return (
    <form className="placeOnShelf" onSubmit={async (event) => {
      event.preventDefault();
      setBusy(true);
      setError("");
      try {
        await api("/api/v1/inventory/transfer/", { method: "POST", body: JSON.stringify({
          variant_id: variant.id, source_id: unplaced.shelf_id, destination_id: shelf, quantity, reference: "PLACE-ON-SHELF" }) });
        setOpen(false);
        onPlaced();
      } catch (e) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    }}>
      <fieldset disabled={busy}>
        <PhysicalLocationPicker zones={zones} value={shelf} onChange={setShelf} required />
        <label>
          Quantity to place
          <input type="number" min="0.001" max={Number(unplaced.available)} step="0.001" required
            value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
        <div className="actionRow">
          <button disabled={!shelf}>Move to this compartment</button>
          <button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button>
        </div>
      </fieldset>
      <FormError title="Could not place the stock." message={error} />
    </form>
  );
}

const when = (value) => (value ? new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const whenTime = (value) => new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const shelfPath = (actual) => actual.shelf__code === UNPLACED ? "Not on a shelf yet"
  : [actual.shelf__zone__name, actual.shelf__level__stack__display_name || "Unassigned rack", `Level ${actual.shelf__level__level_number || "—"}`, actual.shelf__code].join(" › ");

// One product on one page: where it belongs, the figures that matter, its variants, where it is kept,
// where it came from and what has happened to it. Buying prices and profit only for those allowed to see them.
function ProductDetail({ product, categories, selectedVariant, user, zones, onBack, onEdit, onPlaced }) {
  const selection = useProductSelection();
  const service = product.product_type === "SERVICE";
  const [overview, setOverview] = useState(null);
  // The overview is extra detail: if it cannot load, the page still shows the product itself.
  const loadOverview = () => api(`/api/v1/catalog/products/${product.id}/overview/`)
    .then((data) => setOverview(data && data.stock && data.sales_30_days ? data : null)).catch(() => setOverview(null));
  useEffect(() => { void loadOverview(); }, [product.id]);
  // Opening a product starts at the top of its page (not wherever the list was scrolled to). A variant chosen in
  // the search is brought into view once, on opening, so later refreshes never pull the page away from the top.
  const selectedRow = useRef(null);
  useEffect(() => {
    if (selectedVariant && selectedRow.current) selectedRow.current.scrollIntoView?.({ block: "nearest" });
    else window.scrollTo?.({ top: 0 });
  }, [product.id, selectedVariant]);
  useLiveRefresh(loadOverview);
  const stock = overview?.stock;
  const recent = overview?.sales_30_days;
  const showCost = stock && "value_at_cost" in stock;
  const low = !service && product.variants.some((v) => Number(v.available || 0) <= Number(v.minimum_stock || 0));
  const prices = product.variants.map((v) => Number(v.selling_price));
  const floors = product.variants.map((v) => Number(v.minimum_price)).filter(Boolean);
  const bp = product.variants.map((v) => v.latest_bp).filter((v) => v != null).map(Number);
  const range = (values) => (!values.length ? "—" : Math.min(...values) === Math.max(...values) ? money(values[0]) : `${money(Math.min(...values))} – ${Number(Math.max(...values)).toLocaleString()}`);
  const first = product.variants[0];
  const actual = product.locations.flatMap((location) => location.actual.map((row) => ({ ...row, variant_id: location.variant_id })));
  const variantName = (id) => product.variants.find((v) => v.id === id)?.name;
  const filed = categories.find((c) => c.id === product.category);
  return (
    <article className="productPage">
      <button type="button" className="pageBackLink productBack" onClick={onBack}>← Back to {filed ? filed.path.at(-1) : "products"}</button>
      <CategoryCrumbs categories={categories} path={filed?.path || overview?.category_path || [product.category_name]} linkLast />
      <header className="productHero">
        <ProductImage product={{ images: first?.images, product_name: product.name }} />
        <div className="productHeroText">
          <div className="productBadges">
            <span className={`stockBadge${product.active ? "" : " muted"}`}>{product.active ? "Active" : "Hidden"}</span>
            {service ? <span className="stockBadge muted">Service</span> : low && <span className="stockBadge low">Low stock</span>}
            {product.variants.length > 1 && <span className="stockBadge muted">{product.variants.length} variants</span>}
          </div>
          <h1>{product.name}</h1>
          <p className="muted">{[product.brand_name, product.category_name].filter(Boolean).join(" · ")}</p>
          {product.description && <p className="productDescription">{product.description}</p>}
        </div>
        <div className="productHeroActions">
          {!service && product.variants.length === 1 && hasPermission(user, "inventory.add_stockreceipt") && <a className="button" href={`/admin/quick-receive?variant=${first.id}`}>Receive stock</a>}
          {(hasPermission(user, "catalog.change_product") || hasPermission(user, "catalog.change_productvariant")) &&
            <button type="button" className="secondary" onClick={() => onEdit({ product })}>Edit product details</button>}
          {selection?.enabled && <button type="button" className="danger" onClick={() => selection.askDelete([product.id])}>Delete</button>}
        </div>
      </header>

      <section className="productKpis" aria-label="Key figures">
        {!service && <article><span>On the shelf</span><strong>{stock ? count(stock.on_shelf) : "…"}</strong>
          <small>{stock && Number(stock.reserved) ? `${count(stock.available)} free to sell · ${count(stock.reserved)} set aside` : `Restock at ${count(first?.minimum_stock)}`}</small></article>}
        <article><span>Selling price</span><strong>{range(prices)}</strong><small>{floors.length ? `Lowest ${range(floors)}` : "No lowest price set"}</small></article>
        {bp.length > 0 && <article><span>Buying price</span><strong>{range(bp)}</strong><small>Next unit to be sold</small></article>}
        {!service && stock && <article><span>Stock value</span><strong>{money(showCost ? stock.value_at_cost : stock.value_at_selling_price)}</strong>
          <small>{showCost ? `${money(stock.value_at_selling_price)} at selling price` : "At selling price"}</small></article>}
        <article><span>Sold, last 30 days</span><strong>{recent ? count(recent.quantity) : "…"}</strong><small>{recent ? `${money(recent.revenue)} in sales` : ""}</small></article>
        {recent && "profit" in recent && <article className={Number(recent.profit) < 0 ? "loss" : undefined}><span>Profit, last 30 days</span>
          <strong>{Number(recent.profit) < 0 ? `${money(-Number(recent.profit))} loss` : money(recent.profit)}</strong>
          <small>{overview.last_sold ? `Last sold ${when(overview.last_sold)}` : "Not sold yet"}</small></article>}
      </section>

      <section className="productSection" aria-labelledby="variants-heading">
        <h2 id="variants-heading">{product.variants.length > 1 ? "Variants" : "Details"}</h2>
        <div className="trendTable"><table className="productTable">
          <thead><tr><th scope="col">Type</th><th scope="col">Item code</th><th scope="col">Barcode</th><th scope="col">Price</th><th scope="col">Lowest</th>
            {!service && <><th scope="col">In stock</th><th scope="col">Restock at</th></>}<th scope="col"><span className="visuallyHidden">Actions</span></th></tr></thead>
          <tbody>{product.variants.map((variant) => {
            const restock = !service && Number(variant.available || 0) <= Number(variant.minimum_stock || 0);
            return <tr key={variant.id} className={selectedVariant === variant.id ? "selectedRow" : undefined}
              ref={selectedVariant === variant.id ? selectedRow : undefined}>
              <th scope="row">{variant.name || "Standard"}{variant.active ? "" : <small className="muted"> · Hidden</small>}</th>
              <td><code>{variant.sku}</code></td><td>{variant.barcode || "—"}</td>
              <td>{money(variant.selling_price)}</td><td>{Number(variant.minimum_price) ? money(variant.minimum_price) : "—"}</td>
              {!service && <><td><span className={`stockBadge${restock ? " low" : ""}`}>{count(variant.available)}</span></td><td>{count(variant.minimum_stock)}</td></>}
              <td className="rowActions">
                {!service && product.variants.length > 1 && hasPermission(user, "inventory.add_stockreceipt") && <a className="button secondary" href={`/admin/quick-receive?variant=${variant.id}`}>Receive</a>}
              </td>
            </tr>;
          })}</tbody>
        </table></div>
      </section>

      {!service && <section className="productSection" aria-labelledby="kept-heading">
        <h2 id="kept-heading">Where it is kept</h2>
        {!actual.length ? <p className="muted">{product.locations.find((l) => l.preferred_shelf)?.preferred_shelf ? `None on the shelves. Usually kept at ${product.locations.find((l) => l.preferred_shelf).preferred_shelf.code}.` : "None on the shelves, and no usual shelf set."}</p>
          : <ul className="shelfList">{actual.map((row) => {
            const variant = product.variants.find((v) => v.id === row.variant_id);
            return <li key={`${row.variant_id}-${row.shelf_id}`}>
              <span>{row.shelf__code === UNPLACED ? "📦" : "📍"} {shelfPath(row)}{product.variants.length > 1 ? ` · ${variantName(row.variant_id)}` : ""}</span>
              <b>{count(row.available)}</b>
              {row.shelf__code === UNPLACED && Number(row.available) > 0 && hasPermission(user, "inventory.change_stockbalance") &&
                <PlaceOnShelf key={`${row.shelf_id}-${row.available}`} variant={variant} unplaced={row} zones={zones} onPlaced={onPlaced} />}
            </li>;
          })}</ul>}
      </section>}

      <div className="productColumns">
        {!service && <section className="productSection" aria-labelledby="deliveries-heading">
          <h2 id="deliveries-heading">Deliveries</h2>
          {!overview?.deliveries.length ? <p className="muted">No deliveries recorded.</p> : <div className="trendTable"><table className="productTable">
            <thead><tr><th scope="col">Date</th><th scope="col">From</th><th scope="col">Received</th><th scope="col">Left</th>{showCost && <th scope="col">Cost each</th>}</tr></thead>
            <tbody>{overview.deliveries.map((row, index) => <tr key={index}><td>{when(row.date)}</td>
              <td>{row.supplier || (row.reference === "OPENING" ? "Opening stock" : "—")}<br /><small className="muted">{row.reference}</small></td>
              <td>{count(row.received)}</td><td>{count(row.left)}</td>{showCost && <td>{money(row.cost_each)}</td>}</tr>)}</tbody>
          </table></div>}
        </section>}
        <section className="productSection" aria-labelledby="activity-heading">
          <h2 id="activity-heading">Recent activity</h2>
          {!overview?.activity.length ? <p className="muted">Nothing has happened to this product yet.</p> : <ol className="activityList">
            {overview.activity.map((row, index) => <li key={index} className={row.direction}>
              <span className="activityQty">{row.direction === "in" ? "+" : row.direction === "out" ? "−" : "↔"}{count(row.quantity)}</span>
              <span><b>{row.what}</b>{product.variants.length > 1 ? ` · ${row.variant}` : ""}<br />
                <small className="muted">{whenTime(row.date)}{row.shelf ? ` · ${row.shelf}` : ""}{row.reference && row.reference !== "OPENING" ? ` · ${row.reference}` : ""}{row.by ? ` · ${row.by}` : ""}</small></span>
            </li>)}
          </ol>}
        </section>
      </div>
      {overview && <p className="muted productTotals">All time: {count(overview.sales_all_time.quantity)} sold for {money(overview.sales_all_time.revenue)}
        {"profit" in overview.sales_all_time ? `, ${Number(overview.sales_all_time.profit) < 0 ? `${money(-Number(overview.sales_all_time.profit))} loss` : `${money(overview.sales_all_time.profit)} profit`}` : ""}.
        {overview.last_received ? ` Last stock added ${when(overview.last_received)}.` : ""}</p>}
    </article>
  );
}

export function ProductsPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  // Stock just received from a product page, which comes back here to the top of the product's category.
  const received = useLocation().state?.received;
  const productId = params.get("product");
  const selectedVariant = Number(params.get("variant")) || null;
  // The open category (none: the top-level categories) and the page of its products, kept in the address so Back works.
  const category = params.get("category") || "";
  const page = Number(params.get("page")) || 1;
  const setPage = (number) => setParams({ category, page: String(number) });
  const [editing, setEditing] = useState(null);
  // Products of one category page, labelled with the page they belong to so a stale list is never shown.
  const [listing, setListing] = useState(null);
  const [counts, setCounts] = useState(null);
  const [product, setProduct] = useState(null);
  const [zones, setZones] = useState([]);
  const [categories, setCategories] = useState([]);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [templateError, setTemplateError] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  // Deleting: ticked products, the ones being asked about, and what happened.
  const canHide = hasPermission(user, "catalog.change_product");
  const canRemove = hasPermission(user, "catalog.delete_product");
  const [picked, setPicked] = useState(() => new Set());
  const [deleting, setDeleting] = useState(null);
  const [deleted, setDeleted] = useState(null);
  // Deleting starts from the "Delete products" button: one product (a Delete button per row) or several (tick boxes).
  const [deleteMode, setDeleteMode] = useState(null);
  const [choosing, setChoosing] = useState(false);
  const stopDeleting = () => { setDeleteMode(null); setChoosing(false); setPicked(new Set()); };
  const selection = { enabled: canHide || canRemove, mode: deleteMode, selected: picked, askDelete: setDeleting,
    toggle: (id) => setPicked((old) => { const next = new Set(old); if (next.has(id)) next.delete(id); else next.add(id); return next; }) };
  const load = () => {
    setError("");
    const key = `${category}:${page}`;
    return Promise.all([
      category ? api(`/api/v1/catalog/products/?page=${page}&category=${encodeURIComponent(category)}`) : null,
      loadZonesIfUsed(user),
      api("/api/v1/inventory/categories/available/").catch(() => []),
      api("/api/v1/catalog/products/category-counts/").catch(() => ({ categories: {}, other: 0 })),
    ])
      .then(([products, locations, tree, totals]) => {
        setCategories(Array.isArray(tree) ? tree : []);
        setCounts(totals || { categories: {}, other: 0 });
        setListing({ key, rows: products?.results || [], next: Boolean(products?.next) });
        setZones(locations);
      })
      .catch((e) => setError(e.message));
  };
  const loadProduct = () => {
    if (!productId) { setProduct(null); return; }
    api(`/api/v1/catalog/products/${encodeURIComponent(productId)}/`)
      .then((row) => {
        setProduct(row);
        if (params.get("edit") === "product" && (hasPermission(user, "catalog.change_product") || hasPermission(user, "catalog.change_productvariant"))) {
          setEditing({ product: row, variant: selectedVariant ? { id: selectedVariant } : undefined });
          setParams((current) => { current.delete("edit"); return current; }, { replace: true });
        }
      })
      .catch((e) => setError(e.message));
  };
  useEffect(() => {
    void load();
  }, [category, page]);
  useEffect(loadProduct, [productId]);
  // "A similar product" from Receive stock: a new product filled in from an existing one, received once created.
  const similarId = params.get("similar");
  useEffect(() => {
    if (!similarId) return;
    api(`/api/v1/catalog/products/${encodeURIComponent(similarId)}/`).then((row) => {
      const v = row.variants[0] || {};
      setAdding({ similarTo: row.name, name: row.name, description: row.description, category: row.category ? String(row.category) : "",
        brand: row.brand ? String(row.brand) : "", product_type: row.product_type, variant_name: v.name, selling_price: v.selling_price,
        minimum_price: v.minimum_price, minimum_stock: v.minimum_stock, target_stock: v.target_stock, pack_size: v.pack_size,
        piece_name: v.piece_name, shelf: row.locations?.find((l) => l.variant_id === v.id)?.preferred_shelf?.id || "" });
      setParams((current) => { current.delete("similar"); return current; }, { replace: true });
    }).catch((e) => setError(e.message));
  }, [similarId]);
  useLiveRefresh(() => { void load(); loadProduct(); });
  const refresh = () => { void load(); loadProduct(); };
  if (error) return <ErrorState message={error} retry={refresh} />;
  if (!counts) return <Loading />;
  const rows = listing?.key === `${category}:${page}` ? listing.rows : null;
  const next = Boolean(rows && listing.next);
  // Leaving a product goes back to the category it is filed in.
  const backToCategory = () => {
    const filed = product && categories.find((c) => c.id === product.category);
    setParams(filed ? { category: String(filed.id) } : product ? { category: "other" } : {});
  };
  const open = (row) => setParams({ product: String(row.product_id), variant: String(row.id) });
  if (editing)
    return (
      <ProductEditor
        product={product?.id === editing.product.id ? product : editing.product}
        focusVariantId={editing.variant?.id}
        onRefresh={loadProduct}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          refresh();
        }}
        onDeleted={() => {
          setEditing(null);
          setParams({});
          void load();
        }}
      />
    );
  if (adding)
    return (
      <ProductForm
        defaults={adding === true ? {} : adding}
        onClose={() => setAdding(false)}
        zones={zones}
        onSaved={(created) => {
          if (adding?.similarTo && created?.variant_id) { navigate(`/admin/quick-receive?variant=${created.variant_id}`); return; }
          setAdding(false);
          void load();
        }}
      />
    );
  if (importing)
    return (
      <ProductImport
        onClose={() => setImporting(false)}
        onImported={() => {
          setImporting(false);
          void load();
        }}
      />
    );
  const dialog = deleting && <DeleteProductsDialog ids={deleting} canHide={canHide} canRemove={canRemove} onClose={() => setDeleting(null)}
    onDone={(results) => {
      setDeleting(null);
      stopDeleting();
      setDeleted(results);
      if (results.some((row) => String(row.id) === productId && row.result === "removed")) setParams({});
      void load();
      if (productId) loadProduct();
    }} />;
  const done = deleted && <p className="formNotice formNoticeSuccess" role="status">
    {[["removed", "removed permanently"], ["hidden", "deleted with records kept (hidden)"]].map(([key, text]) => {
      const names = deleted.filter((row) => row.result === key).map((row) => row.name);
      return names.length ? `${names.join(", ")}: ${text}. ` : "";
    }).join("")}<button type="button" className="linkButton" onClick={() => setDeleted(null)}>Dismiss</button></p>;
  if (productId)
    return <ProductSelection.Provider value={selection}>{done}
      {product && String(product.id) === productId
        ? <ProductDetail product={product} categories={categories} selectedVariant={selectedVariant} user={user} zones={zones}
            onBack={backToCategory} onEdit={setEditing} onPlaced={refresh} />
        : <Loading />}{dialog}</ProductSelection.Provider>;
  const openCategory = category === "other" ? { id: "other", path: ["Other"] } : categories.find((c) => String(c.id) === category);
  // One level up: the parent folder, or the top of Products.
  const parentCategory = openCategory?.path.length > 1 ? categories.find((c) => samePath(c.path, openCategory.path.slice(0, -1))) : null;
  const tiles = !category ? categories.filter((c) => c.path.length === 1) : category === "other" || !openCategory ? [] : childrenOf(categories, openCategory.path);
  const canDelete = selection.enabled && Boolean(rows?.length);
  return (
    <ProductSelection.Provider value={selection}>
      <div className="heading">
        <div>
          {category ? <>
            <Link className="pageBackLink" to={parentCategory ? `?category=${parentCategory.id}` : "?"}>← Back to {parentCategory?.name || "all products"}</Link>
            <CategoryCrumbs categories={categories} path={openCategory?.path || ["Category not found"]} />
          </> : <BackLink />}
          <span className="eyebrow">Catalog management</span>
          <h1>{category ? openCategory?.path.at(-1) || "Category not found" : "Products"}</h1>
          <p>{category ? "Open a sub-category, or tap a product to see its prices, stock, shelf and types."
            : "Open a category to see its sub-categories and products."}</p>
          {received && <FormSuccess>{received.quantity} × {received.item} added to stock{received.unknownCost ? " (cost pending)" : ""}. <Link to={`/admin/receipts/${received.id}`}>View record {received.receipt_number}</Link></FormSuccess>}
        </div>
        {(hasPermission(user, "catalog.add_product") || canDelete) && (
          <div className="actionRow">
            {canDelete && !deleteMode && <button type="button" className="secondary" onClick={() => setChoosing(true)}>Delete products</button>}
            {hasPermission(user, "catalog.add_product") && <>
              <button type="button" className="secondary" title="An Excel sheet laid out like the Add Product form: fill a row per product, keep adding, then import it"
                onClick={() => downloadTemplate().catch((e) => setTemplateError(e.message))}>
                <FileSpreadsheet size={17} aria-hidden="true" /> Download Excel template</button>
              <button type="button" className="secondary" onClick={() => setImporting(true)}>Import spreadsheet</button>
              <button onClick={() => setAdding(category ? categoryDefaults(openCategory, rows || []) : true)}>Add Product</button>
            </>}
          </div>
        )}
      </div>
      {!category && <StockTotals stock={counts.stock} />}
      {hasPermission(user, "catalog.add_product") && !category && (
        <p className="templateHint">
          <FileSpreadsheet size={18} aria-hidden="true" />
          <span>Adding many products? Download the sample Excel template in the expected format: one row per product, laid out like the
            Add Product form, with your categories and brands to pick from. Keep adding rows to the same file, then use Import spreadsheet.</span>
          <button type="button" className="linkButton" onClick={() => downloadTemplate().catch((e) => setTemplateError(e.message))}>Download template</button>
        </p>
      )}
      <FormError title="Could not download the template." message={templateError} />
      <ProductSearch
        value={query}
        onChange={setQuery}
        endpoint="/api/v1/catalog/products/search-suggestions/"
        minLength={1}
        limit={30}
        onSelect={open}
        onSearch={() => {}}
        exactScan
        renderResult={(row) => <VariantSummary row={row} />}
      />
      {done}
      {choosing && !deleteMode && <div className="productSelectionBar" role="region" aria-label="Delete products">
        <span>Delete one product or several?</span>
        <button type="button" className="secondary" onClick={() => { setDeleteMode("one"); setChoosing(false); }}>One product</button>
        <button type="button" className="secondary" onClick={() => { setDeleteMode("many"); setChoosing(false); }}>Several products</button>
        <button type="button" className="linkButton" onClick={stopDeleting}>Cancel</button>
      </div>}
      {deleteMode === "one" && <div className="productSelectionBar" role="region" aria-label="Delete products">
        <span>Press <b>Delete</b> on the product you want to remove.</span>
        <button type="button" className="linkButton" onClick={stopDeleting}>Cancel</button>
      </div>}
      {deleteMode === "many" && <div className="productSelectionBar" role="region" aria-label="Delete products">
        <span>Tick the products to delete · <b>{picked.size}</b> selected</span>
        <button type="button" className="danger" disabled={!picked.size} onClick={() => setDeleting([...picked])}>Delete selected</button>
        <button type="button" className="linkButton" onClick={stopDeleting}>Cancel</button>
      </div>}
      <CategoryCards categories={categories} counts={counts} items={tiles} other={category ? 0 : counts.other} />
      {category && !rows && <Loading />}
      {rows?.length > 0 && <>
        {tiles.length > 0 && <h2 className="productGroup parent">Products in {openCategory.path.at(-1)}</h2>}
        <RestockFirst rows={rows} />
      </>}
      {!category && !tiles.length && !counts.other && <Empty>No products yet. Create the first product and assign its real location.</Empty>}
      {category && rows && !rows.length && !tiles.length && page === 1 && <Empty>No products in this category yet.</Empty>}
      {(page > 1 || next) && <nav className="actionRow" aria-label="Catalogue pages">
        <button type="button" className="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="muted">Page {page}</span>
        <button type="button" className="secondary" disabled={!next} onClick={() => setPage(page + 1)}>Next</button>
      </nav>}
      {dialog}
    </ProductSelection.Provider>
  );
}
