import { ProductSkuField } from "./components/ProductSkuField";
import { FormField } from "../../components/forms/FormField";
import { useEffect, useState } from "react";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";
import { api } from "../../core/api/client";
export function ProductForm({ zones, onSaved, preferredShelf }) {
  const [categories, setCategories] = useState([]);
  const [brands, setBrands] = useState([]);
  const [productName, setProductName] = useState("");
  const [variantName, setVariantName] = useState("Standard");
  const [type, setType] = useState("STOCK_ITEM");
  const [shelf, setShelf] = useState(preferredShelf);
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([
      api("/api/v1/inventory/categories/available/"),
      api("/api/v1/catalog/brands/"),
    ]).then(([c, b]) => {
      setCategories(c);
      setBrands(b);
    });
  }, []);
  const save = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      await api("/api/v1/catalog/products/create-with-stock/", {
        method: "POST",
        body: JSON.stringify({
          ...data,
          preferred_shelf_id: type === "STOCK_ITEM" ? shelf : null,
          ecommerce_visible: data.ecommerce_visible === "on",
          online_orderable: data.online_orderable === "on",
        }),
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="formCard productForm" onSubmit={save}>
      <h2>Add Product</h2>
      {error && <p className="formError">{error}</p>}
      <FormField
        label="Product name"
        name="name"
        required
        value={productName}
        onChange={(event) => setProductName(event.target.value)}
      />
      <label>
        Product category — what kind of item is this?
        <select name="category_id" required>
          {categories.map((c) => (
            <option value={c.id} key={c.id}>
              {c.name} — available in {c.rack_names?.join(", ")}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        Categories organize products for stock management and the online shop.
        Physical storage is selected separately.
      </p>
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
          <option value="SERVICE">Billable service</option>
        </select>
      </label>
      <label>
        {type === "SERVICE" ? "Service option" : "Variant"}
        <input
          name="variant_name"
          value={variantName}
          onChange={(event) => setVariantName(event.target.value)}
          required
        />
      </label>
      <ProductSkuField
        productName={productName}
        variantName={variantName}
        zones={zones}
        shelfId={shelf}
        productType={type}
      />
      {type === "STOCK_ITEM" && <FormField label="Barcode" name="barcode" />}
      <FormField label="Product image URL (optional)" name="image_url" type="url" />
      <p className="muted">
        Leave the image URL empty to randomly select an AI illustration matching
        the product name and category. Your own image URL takes priority.
      </p>
      <FormField
        label="Selling price"
        name="selling_price"
        type="number"
        min="0"
        step=".01"
        required
      />
      {type === "SERVICE" ? (
        <>
          <FormField
            label="Service cost"
            name="service_cost"
            type="number"
            min="0"
            step=".01"
            defaultValue="0"
          />
          <p className="muted serviceHint">
            Examples: Windows installation, Microsoft Office setup, drivers,
            antivirus, printing, scanning, typing or application installation.
            M-Pesa agency operations belong in the separate M-Pesa desk.
          </p>
        </>
      ) : (
        <>
          <FormField
            label="Minimum stock"
            name="minimum_stock"
            type="number"
            min="0"
            step=".001"
            defaultValue="0"
          />
          <FormField
            label="Target stock"
            name="target_stock"
            type="number"
            min="0"
            step=".001"
            defaultValue="0"
          />
        </>
      )}
      <label>
        <input name="ecommerce_visible" type="checkbox" defaultChecked />{" "}
        Visible online
      </label>
      <label>
        <input name="online_orderable" type="checkbox" defaultChecked /> Can be
        purchased through online checkout
      </label>
      {type === "STOCK_ITEM" && (
        <>
          <PhysicalLocationPicker
            zones={zones}
            value={shelf}
            onChange={setShelf}
          />
          <FormField
            label="Opening buying price"
            name="opening_unit_cost"
            type="number"
            min="0"
            step=".01"
            defaultValue="0"
          />
          <FormField
            label="Opening quantity"
            name="opening_quantity"
            type="number"
            min="0"
            step=".001"
            defaultValue="0"
          />
        </>
      )}
      <button>Create Product</button>
    </form>
  );
}
