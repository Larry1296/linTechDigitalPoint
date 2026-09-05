import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useCart } from "../../core/cart/CartContext";
import { ErrorState, Loading } from "../../components/States";
import type { Product } from "../../types";
function availability(value: string | null) {
  if (value === null) return "Available";
  const count = +value;
  return count <= 0
    ? "Out of stock"
    : count <= 3
      ? "Only " + count + " left"
      : "In stock";
}
export function ProductPage() {
  const { id } = useParams();
  const [p, setP] = useState<Product>();
  const [error, setError] = useState("");
  const nav = useNavigate();
  const { refreshCart } = useCart();
  useEffect(() => {
    api<Product>("/api/v1/store/products/" + id + "/")
      .then((product) => {
        setP(product);
        document.title = product.product_name + " | LinTech Digital Point";
      })
      .catch((e) => setError(e.message));
  }, [id]);
  if (error)
    return (
      <main>
        <ErrorState message={error} />
      </main>
    );
  if (!p) return <Loading />;
  const add = async () => {
    await api("/api/v1/commerce/cart/", {
      method: "POST",
      body: JSON.stringify({ variant_id: p.id, quantity: 1 }),
    });
    await refreshCart();
    nav("/cart");
  };
  return (
    <main className="productDetail">
      <div className="productImage large">
        {p.images[0] ? (
          <img src={p.images[0].url} alt={p.images[0].alt} />
        ) : (
          p.product_name[0]
        )}
      </div>
      <section>
        <span className="eyebrow">{p.category}</span>
        <h1>{p.product_name}</h1>
        {p.name !== "Standard" && <h3>{p.name}</h3>}
        <p>{p.description || "A quality choice from LinTech Digital Point."}</p>
        <strong className="price">KSh {p.selling_price}</strong>
        <p className="stock">{availability(p.available)}</p>
        <button
          onClick={() => void add()}
          disabled={!p.online_orderable || (p.available !== null && +p.available <= 0)}
        >
          {p.online_orderable ? "Add to cart" : "Available in store"}
        </button>
      </section>
    </main>
  );
}
