import { useState } from "react";
import { api } from "../../core/api/client";
import { DisplayImageInput } from "./components/DisplayImageInput";
import { FormError } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";

export function ProductPhotos({
  product,
  onSaved,
  onClose,
  canCreateVariant = false,
  embedded = false,
}) {
  const [scope, setScope] = useState(
    product.selectedVariantId ? String(product.selectedVariantId) : "",
  );
  const [file, setFile] = useState(null);
  const [reuse, setReuse] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const variant = product.variants.find((item) => String(item.id) === scope);
  const main = product.images?.find((image) => !image.variant);
  const existingUrl = variant
    ? variant.images?.[0]?.url
    : main?.file || main?.image_url;
  const submit = async (event) => {
    event.preventDefault();
    if (!file && !(reuse && (scope || adding))) {
      setError("Choose a Product display image to upload.");
      return;
    }
    const data = new FormData(event.currentTarget);
    if (file) data.set("display_image", file);
    data.set("use_product_image", String(reuse));
    if (!adding && scope) data.set("variant_id", scope);
    setSaving(true);
    setError("");
    try {
      await api(
        `/api/v1/catalog/products/${product.id}/${adding ? "variants" : "display-image"}/`,
        { method: "POST", body: data },
      );
      if (embedded) {
        setFile(null);
        setReuse(false);
        setAdding(false);
        event.target.reset?.();
      }
      onSaved();
    } catch (error) {
      setError(error.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <section className="panel" aria-label="Photos">
      {!embedded && <button type="button" className="pageBackLink" onClick={onClose}>← Back</button>}
      {embedded ? <h3>Photos and new types</h3> : <h2>Display photos — {product.name}</h2>}
      <p>
        Use a separate photograph of each cable package. Do not use a group
        photo containing Type-B and Type-C together.
      </p>
      {canCreateVariant && (
        <button
          type="button"
          className="secondary"
          onClick={() => {
            setAdding(!adding);
            setFile(null);
            setReuse(false);
            setError("");
          }}
        >
          {adding ? "Edit existing photos" : "Add another type"}
        </button>
      )}
      <form onSubmit={submit}>
        <fieldset disabled={saving}>
          {adding ? (
            <>
              <label>
                Variant name
                <TextBox name="variant_name" required maxLength={120} />
              </label>
              <label>
                SKU
                <TextBox name="sku" required maxLength={64} />
              </label>
              <label>
                Selling price
                <input
                  name="selling_price"
                  type="number"
                  min="0"
                  step="0.01"
                  required
                />
              </label>
              <label>
                Lowest price (bargaining guide, optional)
                <input name="minimum_price" type="number" min="0" step="0.01" />
              </label>
            </>
          ) : (
            <label>
              Image applies to
              <select
                value={scope}
                onChange={(event) => {
                  setScope(event.target.value);
                  setFile(null);
                  setReuse(false);
                }}
              >
                <option value="">Primary product image</option>
                {product.variants.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.sku}
                  </option>
                ))}
              </select>
            </label>
          )}
          {(scope || adding) && (
            <label>
              <input
                type="checkbox"
                checked={reuse}
                onChange={(event) => {
                  setReuse(event.target.checked);
                  setFile(null);
                }}
              />
              Reuse the product's main image (only if it shows this exact
              variant)
            </label>
          )}
          {!reuse && (
            <DisplayImageInput
              file={file}
              onChange={setFile}
              existingUrl={adding ? "" : existingUrl}
              required
            />
          )}
          <button>
            {saving
              ? "Saving…"
              : adding
                ? "Add type"
                : "Save display image"}
          </button>
          {!embedded && <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>}
          <FormError title={adding ? "Could not add the type." : "Could not save the display image."} message={error} />
        </fieldset>
      </form>
    </section>
  );
}
