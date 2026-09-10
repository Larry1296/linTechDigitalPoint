import { ProductSearch } from "./components/ProductSearch";
import { ProductCard } from "./components/ProductCard";
import { useEffect, useState } from "react";
import {
  Link,
  useLocation,
  useNavigationType,
  useSearchParams,
} from "react-router-dom";
import { restoreListingPosition } from "./listingPosition";
import { api } from "../../core/api/client";
import { useCart } from "../../core/cart/CartContext";
import { Empty, ErrorState, Loading } from "../../components/States";
export function ShopPage() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigationType = useNavigationType();
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState(params.get("search") || "");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { addToCart } = useCart();
  const [reload, setReload] = useState(0);
  const load = () => setReload((count) => count + 1);
  useEffect(() => {
    let current = true;
    document.title = "Shop | LinTech Digital Point";
    setLoading(true);
    setError("");
    const search = new URLSearchParams();
    search.set("in_stock", "true");
    if (params.get("search")) search.set("search", params.get("search"));
    if (params.get("category"))
      search.set("product__category", params.get("category"));
    api("/api/v1/store/products/?" + search)
      .then((data) => {
        if (current) setRows(data);
      })
      .catch((e) => {
        if (current) setError(e.message);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [params, reload]);
  useEffect(() => {
    setQuery(params.get("search") || "");
  }, [params]);
  useEffect(() => {
    if (loading || error || navigationType !== "POP") return;
    const frame = window.requestAnimationFrame(() =>
      restoreListingPosition(location.key),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [loading, error, rows, location.key, navigationType]);
  const add = (product) => addToCart(product.id);
  return (
    <main className="shopPage">
      {params.get("category") && (
        <Link className="button secondary" to="/#categories">
          ← Back to categories
        </Link>
      )}
      <div className="heading">
        <div>
          <span className="eyebrow">Products & accessories</span>
          <h1>Shop</h1>
          <p className="muted">
            Browse products and everyday essentials available from LinTech
            Digital Point.
          </p>
        </div>
        <ProductSearch
          value={query}
          onChange={setQuery}
          onSearch={(text) => {
            const next = new URLSearchParams(params);
            if (text) next.set("search", text);
            else next.delete("search");
            setParams(next);
          }}
        />
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} retry={load} />
      ) : !rows.length ? (
        <Empty>No products match your search.</Empty>
      ) : (
        <div className="productGrid">
          {rows.map((p) => (
            <ProductCard key={p.id} product={p} onAdd={add} />
          ))}
        </div>
      )}
    </main>
  );
}
