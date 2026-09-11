import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
export function ProductEditor({ product, variant, onSaved, onClose }) {
  const [data, setData] = useState(variant || product);
  const [categories, setCategories] = useState([]);
  const [brands, setBrands] = useState([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!variant)
      Promise.all([
        api("/api/v1/catalog/categories/"),
        api("/api/v1/catalog/brands/"),
      ])
        .then(([c, b]) => {
          setCategories(c);
          setBrands(b);
        })
        .catch((e) => setError(e.message));
  }, [variant]);
  const fields = variant
    ? [
        "name",
        "sku",
        "barcode",
        "selling_price",
        "minimum_stock",
        "target_stock",
        "active",
      ]
    : [
        "name",
        "category",
        "brand",
        "description",
        "active",
        "ecommerce_visible",
        "online_orderable",
      ];
  const labels = {
    name: variant ? "Variant name" : "Product name",
    sku: "SKU",
    barcode: "Barcode",
    selling_price: "Selling price",
    minimum_stock: "Minimum stock",
    target_stock: "Target stock",
    active: "Active",
    ecommerce_visible: "Ecommerce visibility",
    online_orderable: "Online-orderable",
    category: "Category",
    brand: "Brand",
    description: "Description",
  };
  return (
    <form
      className="panel"
      onSubmit={async (e) => {
        e.preventDefault();
        setSaving(true);
        setError("");
        try {
          await api(
            `/api/v1/catalog/${variant ? "variants" : "products"}/${data.id}/`,
            {
              method: "PATCH",
              body: JSON.stringify(
                Object.fromEntries(
                  fields.map((f) => [
                    f,
                    f === "barcode" || f === "brand"
                      ? data[f] || null
                      : data[f],
                  ]),
                ),
              ),
            },
          );
          onSaved();
        } catch (e) {
          setError(e.message);
        } finally {
          setSaving(false);
        }
      }}
    >
      <h2>{variant ? "Edit variant" : "Edit product details"}</h2>
      {error && <p role="alert">{error}</p>}
      {fields.map((field) => (
        <label key={field}>
          {labels[field]}
          {["category", "brand"].includes(field) ? (
            <select
              value={data[field] || ""}
              onChange={(e) => setData({ ...data, [field]: e.target.value })}
            >
              {field === "brand" && <option value="">No brand</option>}
              {(field === "brand" ? brands : categories).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              type={
                typeof data[field] === "boolean"
                  ? "checkbox"
                  : ["selling_price", "minimum_stock", "target_stock"].includes(
                        field,
                      )
                    ? "number"
                    : "text"
              }
              min="0"
              step="any"
              checked={
                typeof data[field] === "boolean" ? data[field] : undefined
              }
              value={data[field] ?? ""}
              onChange={(e) =>
                setData({
                  ...data,
                  [field]:
                    e.target.type === "checkbox"
                      ? e.target.checked
                      : e.target.value,
                })
              }
            />
          )}
        </label>
      ))}
      <button disabled={saving}>Save changes</button>
      <button type="button" className="secondary" onClick={onClose}>
        Cancel
      </button>
    </form>
  );
}
