import { useEffect, useState } from "react";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";
import { api } from "../../core/api/client";
import type { Zone } from "../../types";

type Choice = { id: number; name: string };
export function ProductForm({
  zones,
  onSaved,
  preferredShelf,
}: {
  zones: Zone[];
  onSaved: () => void;
  preferredShelf?: number;
}) {
  const [categories, setCategories] = useState<Choice[]>([]);
  const [brands, setBrands] = useState<Choice[]>([]);
  const [type, setType] = useState("STOCK_ITEM");
  const [shelf, setShelf] = useState(preferredShelf);
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([
      api<Choice[]>("/api/v1/catalog/categories/"),
      api<Choice[]>("/api/v1/catalog/brands/"),
    ]).then(([c, b]) => {
      setCategories(c);
      setBrands(b);
    });
  }, []);
  const save = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      await api("/api/v1/catalog/products/create-with-stock/", {
        method: "POST",
        body: JSON.stringify({
          ...data,
          preferred_shelf_id: type === "STOCK_ITEM" ? shelf : null,
          ecommerce_visible: data.ecommerce_visible === "on",
        }),
      });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form className="formCard productForm" onSubmit={save}>
      <h2>Add Product</h2>
      {error && <p className="formError">{error}</p>}
      <label>
        Product name
        <input name="name" required />
      </label>
      <label>
        Category
        <select name="category_id" required>
          {categories.map((c) => (
            <option value={c.id} key={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Brand
        <select name="brand_id">
          <option value="">No brand</option>
          {brands.map((b) => (
            <option value={b.id} key={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Description
        <textarea name="description" />
      </label>
      <label>
        Product type
        <select
          name="product_type"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="STOCK_ITEM">Stock item</option>
          <option value="SERVICE">Service (M-Pesa / software)</option>
        </select>
      </label>
      <label>
        {type === "SERVICE" ? "Service option" : "Variant"}
        <input name="variant_name" defaultValue="Standard" required />
      </label>
      <label>
        {type === "SERVICE" ? "Service code" : "SKU"}
        <input name="sku" required />
      </label>
      {type === "STOCK_ITEM" && (
        <label>
          Barcode
          <input name="barcode" />
        </label>
      )}
      <label>
        Product image URL
        <input name="image_url" type="url" />
      </label>
      <label>
        Selling price
        <input name="selling_price" type="number" min="0" step=".01" required />
      </label>
      {type === "SERVICE" ? (
        <>
          <label>
            Service cost
            <input
              name="service_cost"
              type="number"
              min="0"
              step=".01"
              defaultValue="0"
            />
          </label>
          <p className="muted serviceHint">
            Examples: Windows installation, Microsoft Office setup, drivers,
            antivirus, application installation or an M-Pesa service. Services
            do not use shelves or stock quantities.
          </p>
        </>
      ) : (
        <>
          <label>
            Minimum stock
            <input
              name="minimum_stock"
              type="number"
              min="0"
              step=".001"
              defaultValue="0"
            />
          </label>
          <label>
            Target stock
            <input
              name="target_stock"
              type="number"
              min="0"
              step=".001"
              defaultValue="0"
            />
          </label>
        </>
      )}
      <label>
        <input name="ecommerce_visible" type="checkbox" defaultChecked />{" "}
        Visible online
      </label>
      {type === "STOCK_ITEM" && (
        <>
          <PhysicalLocationPicker
            zones={zones}
            value={shelf}
            onChange={setShelf}
          />
          <label>
            Opening buying price
            <input
              name="opening_unit_cost"
              type="number"
              min="0"
              step=".01"
              defaultValue="0"
            />
          </label>
          <label>
            Opening quantity
            <input
              name="opening_quantity"
              type="number"
              min="0"
              step=".001"
              defaultValue="0"
            />
          </label>
        </>
      )}
      <button>Create Product</button>
    </form>
  );
}
