import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "../../components/States";
import { api } from "../../core/api/client";
import { ProductForm } from "./ProductForm";
export function ProductsPage() {
  const [rows, setRows] = useState();
  const [zones, setZones] = useState([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const load = () =>
    Promise.all([
      api("/api/v1/catalog/products/"),
      api("/api/v1/locations/zones/"),
    ])
      .then(([products, locations]) => {
        setRows(products);
        setZones(locations);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!rows) return <Loading />;
  if (adding)
    return (
      <ProductForm
        zones={zones}
        onSaved={() => {
          setAdding(false);
          void load();
        }}
      />
    );
  return (
    <>
      <div className="heading">
        <div>
          <span className="eyebrow">Catalog and physical placement</span>
          <h1>Products</h1>
        </div>
        <button onClick={() => setAdding(true)}>Add Product</button>
      </div>
      {rows.length ? (
        rows.map((product) => (
          <article className="panel" key={product.id}>
            <h2>{product.name}</h2>
            <span>
              Category: {product.category_name || product.category}
              {product.product_type === "SERVICE"
                ? "Service — no shelf required"
                : "Stock item"}
            </span>
            {product.variants.map((variant) => {
              const location = product.locations.find(
                (item) => item.variant_id === variant.id,
              );
              return (
                <div className="productLocation" key={variant.id}>
                  <b>
                    {variant.name} · {variant.sku} · Latest BP {variant.latest_bp ?? "—"} · SP KSh {variant.selling_price} · Physical {variant.physical ?? 0} · Reserved {variant.reserved ?? 0} · Available {variant.available ?? 0}
                  </b>
                  <span>
                    {location?.preferred_shelf
                      ? `✓ Preferred: ${location.preferred_shelf.code} — ${location.preferred_shelf.display_name}`
                      : "⚠ No preferred physical shelf"}
                  </span>
                  {location?.actual.map((actual) => (
                    <small key={actual.shelf_id}>
                      Actual: {actual.shelf__zone__name} →{" "}
                      {actual.shelf__level__stack__display_name ||
                        "Unassigned stack"}{" "}
                      → Level {actual.shelf__level__level_number || "—"} →{" "}
                      {actual.shelf__code}: {actual.available} available
                    </small>
                  ))}
                </div>
              );
            })}
          </article>
        ))
      ) : (
        <Empty>
          No products yet. Create the first product and assign its real
          location.
        </Empty>
      )}
    </>
  );
}
