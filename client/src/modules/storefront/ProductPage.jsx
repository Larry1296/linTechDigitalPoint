import { businessCurrency } from "../../core/organization/presentation";
import { ProductImage } from "./components/ProductImage";
import { StockAvailability } from "./components/StockAvailability";
import { AddToCartButton } from "./components/AddToCartButton";
import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../../core/api/client";
import { useCart } from "../../core/cart/CartContext";
import { ErrorState, Loading } from "../../components/States";
import { FormError } from "../../components/forms/FormNotice";
export function ProductPage() {
  const location = useLocation();
  const { id } = useParams();
  const [p, setP] = useState();
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const nav = useNavigate();
  const { addToCart } = useCart();
  useEffect(() => {
    let current = true;
    setP(undefined);
    setSelectedId("");
    setError("");
    api("/api/v1/store/products/" + id + "/")
      .then((product) => {
        if (!current) return;
        setP(product);
        setSelectedId(product.variants.length === 1 ? String(product.id) : "");
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [id]);
  const selected = p?.variants.find(
    (variant) => String(variant.id) === selectedId,
  );
  const shown = selected || p;
  useEffect(() => {
    if (shown) document.title = shown.display_name + " | LinTech Digital Point";
  }, [shown]);
  const backButton = (
    <button
      type="button"
      className="secondary productBackButton"
      onClick={() => {
        if (location.state?.fromListing || window.history.state?.idx > 0)
          nav(-1);
        else nav("/shop", { replace: true });
      }}
    >
      ← Back
    </button>
  );
  if (!p)
    return (
      <main>
        {backButton}
        {error ? <ErrorState message={error} /> : <Loading />}
      </main>
    );
  const add = async () => {
    if (!selected || adding) return;
    setAdding(true);
    setError("");
    try {
      await addToCart(selected.variant_id);
      nav("/cart");
    } catch (e) {
      setError(e.message);
    } finally {
      setAdding(false);
    }
  };
  return (
    <main className="productDetail">
      {backButton}
      <ProductImage product={shown} large />
      <section>
        <span className="eyebrow">{shown.category}</span>
        <h1>{shown.display_name}</h1>
        {p.variants.length > 1 && (
          <label>
            Choose a variant
            <select
              value={selectedId}
              onChange={(event) => {
                setSelectedId(event.target.value);
                setError("");
              }}
            >
              <option value="">Select connector, model and colour</option>
              {p.variants.map((variant) => (
                <option key={variant.id} value={variant.id}>
                  {variant.display_name} — {businessCurrency()} {variant.selling_price}
                  {variant.available !== null && Number(variant.available) <= 0
                    ? " — Out of stock"
                    : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        <p>SKU: {shown.sku}</p>
        {shown.attributes?.length > 0 && (
          <dl>
            {shown.attributes.map((attribute) => (
              <div key={attribute.name}>
                <dt>{attribute.name}</dt>
                <dd>{attribute.value}</dd>
              </div>
            ))}
          </dl>
        )}
        <p>
          {shown.description || "A quality choice from LinTech Digital Point."}
        </p>
        {shown.images?.[0]?.url?.startsWith("/images/catalog/") && (
          <p className="muted">
            AI illustration. Actual model and appearance may vary.
          </p>
        )}
        <strong className="price">{businessCurrency()} {shown.selling_price}</strong>
        <StockAvailability available={shown.available} as="p" />
        {selected && !adding ? (
          <AddToCartButton
            product={selected}
            onAdd={add}
            unavailableLabel="Available in store"
          />
        ) : (
          <button disabled>
            {adding ? "Adding…" : "Choose an option to add to cart"}
          </button>
        )}
        <FormError title="Could not add to cart." message={error} />
      </section>
    </main>
  );
}
