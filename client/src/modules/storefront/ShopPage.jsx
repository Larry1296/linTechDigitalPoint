import { ProductCard } from "./components/ProductCard";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useCart } from "../../core/cart/CartContext";
import { Empty, ErrorState, Loading } from "../../components/States";
export function ShopPage() {
  const [params] = useSearchParams();
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { addToCart } = useCart();
  const load = () => {
    const search = new URLSearchParams();
    if (query) search.set("search", query);
    if (params.get("category"))
      search.set("product__category", params.get("category"));
    api("/api/v1/store/products/?" + search)
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    document.title = "Shop | LinTech Digital Point";
    void load();
  }, [params]);
  const add = (product) => addToCart(product.id);
  return (
    <main>
      <div className="heading">
        <div>
          <span className="eyebrow">Products & accessories</span>
          <h1>Shop</h1>
          <p className="muted">
            Browse products and everyday essentials available from LinTech
            Digital Point.
          </p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            load();
          }}
        >
          <input
            aria-label="Search products"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What are you looking for?"
          />
          <button>Search</button>
        </form>
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
