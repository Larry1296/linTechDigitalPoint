import { ProductImage } from "./components/ProductImage";
import { StockAvailability } from "./components/StockAvailability";
import { AddToCartButton } from "./components/AddToCartButton";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useCart } from "../../core/cart/CartContext";
import { ErrorState, Loading } from "../../components/States";
export function ProductPage() {
  const { id } = useParams();
  const [p, setP] = useState();
  const [error, setError] = useState("");
  const nav = useNavigate();
  const { addToCart } = useCart();
  useEffect(() => {
    api("/api/v1/store/products/" + id + "/")
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
    await addToCart(p.id);
    nav("/cart");
  };
  return (
    <main className="productDetail">
      <ProductImage product={p} large />
      <section>
        <span className="eyebrow">{p.category}</span>
        <h1>{p.product_name}</h1>
        {p.name !== "Standard" && <h3>{p.name}</h3>}
        <p>{p.description || "A quality choice from LinTech Digital Point."}</p>
        <strong className="price">KSh {p.selling_price}</strong>
        <StockAvailability available={p.available} as="p" />
        <AddToCartButton
          product={p}
          onAdd={add}
          unavailableLabel="Available in store"
        />
      </section>
    </main>
  );
}
