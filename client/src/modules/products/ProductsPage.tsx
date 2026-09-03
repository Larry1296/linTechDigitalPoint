import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "../../components/States";
import { api } from "../../core/api/client";
import type { Zone } from "../../types";
import { ProductForm } from "./ProductForm";

type AdminProduct = {
  id: number;
  name: string;
  product_type: string;
  variants: { id: number; name: string; sku: string; selling_price: string }[];
  locations: {
    variant_id: number;
    preferred_shelf: { id: number; code: string; display_name: string } | null;
    actual: {
      shelf_id: number;
      shelf__code: string;
      shelf__display_name: string;
      shelf__zone__name: string;
      shelf__level__level_number: number | null;
      shelf__level__stack__display_name: string | null;
      quantity: string;
      available: string;
    }[];
  }[];
};
export function ProductsPage() {
  const [rows, setRows] = useState<AdminProduct[]>();
  const [zones, setZones] = useState<Zone[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const load = () =>
    Promise.all([
      api<AdminProduct[]>("/api/v1/catalog/products/"),
      api<Zone[]>("/api/v1/locations/zones/"),
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
                    {variant.name} · {variant.sku} · KSh {variant.selling_price}
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
