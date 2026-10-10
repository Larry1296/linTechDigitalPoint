import { useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { FormError } from "../../components/forms/FormNotice";
import { confirmAction } from "../../core/ui/alerts";
import { useAuth } from "../../core/auth/AuthContext";
import { businessCurrency } from "../../core/organization/presentation";
import { ProductPhotos } from "./ProductPhotos";
import { hasPermission } from "./VariantSummary";

const labels = {
  name: "Product name",
  category: "Category",
  brand: "Brand",
  product_type: "Product type",
  description: "Description",
  active: "Active",
  ecommerce_visible: "Show in the online shop",
  online_orderable: "Can be ordered online",
  variant_name: "Type (e.g. size or colour)",
  sku: "SKU",
  barcode: "Barcode",
  selling_price: "Selling price",
  minimum_price: "Lowest price (bargaining guide, 0 = none)",
  service_cost: "Service cost",
  minimum_stock: "Minimum stock",
  target_stock: "Target stock",
};
const productFields = ["name", "category", "brand", "product_type", "description", "active", "ecommerce_visible", "online_orderable"];
const numeric = ["selling_price", "minimum_price", "service_cost", "minimum_stock", "target_stock"];
const checkboxes = ["active", "ecommerce_visible", "online_orderable"];
// service_cost is only sent by the server to staff who may see profit, so it is only editable for them.
const variantFields = (variant, isService) => [
  "name", "sku", "barcode", "selling_price", "minimum_price",
  ...(isService && "service_cost" in variant ? ["service_cost"] : []),
  ...(isService ? [] : ["minimum_stock", "target_stock"]),
  "active",
];
const payload = (row, fields) =>
  Object.fromEntries(fields.map((f) => [f, f === "barcode" || f === "brand" ? row[f] || null : row[f]]));
const changed = (row, original, fields) => fields.some((f) => row[f] !== original?.[f]);
// A number box gives "" when it is empty or holds something that is not a number (e.g. the letter O typed for a zero),
// which the server rejects without naming the box. Name it here instead.
const badNumber = (row, fields) => fields.find((f) => numeric.includes(f) && (row[f] === "" || row[f] == null || Number.isNaN(Number(row[f]))));

const QUANTITY_REASONS = ["Data-entry correction", "Physical count variance", "Found stock", "Damaged item", "Lost item"];
const count = (value) => Number(value || 0);

// Every detail of a product is edited here: the product itself, each variant's codes, prices, buying price, quantity
// and stock levels, and photos. The buying price shown is the latest delivery's: changing it revalues that stock and,
// for a supplier delivery, what is owed. A quantity change is posted as a stock adjustment. Both need a reason.
export function ProductEditor({ product, focusVariantId, onSaved, onDeleted, onClose, onRefresh }) {
  const { user } = useAuth();
  const canProduct = hasPermission(user, "catalog.change_product");
  const canVariant = hasPermission(user, "catalog.change_productvariant");
  const [data, setData] = useState(product);
  const [variants, setVariants] = useState(product.variants || []);
  const [categories, setCategories] = useState([]);
  const [brands, setBrands] = useState([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [latestLot, setLatestLot] = useState({});
  const [stock, setStock] = useState({});
  const [bp, setBp] = useState({});
  const [qty, setQty] = useState({});
  const [quantityReason, setQuantityReason] = useState(QUANTITY_REASONS[0]);
  const [why, setWhy] = useState("");
  const canSeeCost = hasPermission(user, "accounting.view_profit");
  const canAdjust = hasPermission(user, "inventory.adjust_stock");
  const isService = data.product_type === "SERVICE";
  const multiple = variants.length > 1;
  const original = (id) => product.variants?.find((v) => v.id === id);
  // A type added from the photos section joins the list without losing anything typed so far.
  useEffect(() => {
    setVariants((rows) => [...rows, ...(product.variants || []).filter((v) => !rows.some((r) => r.id === v.id))]);
  }, [product.variants]);
  useEffect(() => {
    Promise.all([api("/api/v1/catalog/categories/"), api("/api/v1/catalog/brands/")])
      .then(([c, b]) => {
        setCategories(c);
        setBrands(b);
      })
      .catch((e) => setError(e.message));
  }, []);
  const variantIds = variants.map((v) => v.id).join(",");
  // Each variant's latest delivery (its buying price) and where its stock is (for the quantity).
  useEffect(() => {
    if (product.product_type === "SERVICE") return;
    const each = (path, keep) => Promise.all(variants.map((v) => api(path(v.id)).then((row) => [v.id, keep(row)])))
      .then(Object.fromEntries).catch((e) => { setError(e.message); return {}; });
    if (canSeeCost)
      void each((id) => `/api/v1/inventory/variants/${id}/buying-prices/`, (rows) => rows[0] || null).then((rows) => {
        setLatestLot(rows);
        setBp((typed) => ({ ...Object.fromEntries(Object.entries(rows).map(([id, lot]) => [id, lot?.buying_price ?? ""])), ...typed }));
      });
    if (canAdjust)
      void each((id) => `/api/v1/inventory/adjustments/variants/${id}/`, (row) => row).then((rows) => {
        setStock(rows);
        setQty((typed) => ({ ...Object.fromEntries(Object.entries(rows).map(([id, row]) => [id, String(row.locations.reduce((t, l) => t + count(l.quantity), 0))])), ...typed }));
      });
  }, [variantIds, canSeeCost, canAdjust]);
  const onHand = (id) => (stock[id]?.locations || []).reduce((t, l) => t + count(l.quantity), 0);
  const changedBp = variants.filter((v) => latestLot[v.id] && bp[v.id] !== "" && bp[v.id] !== undefined && count(bp[v.id]) !== count(latestLot[v.id].buying_price ?? NaN));
  const changedQty = variants.filter((v) => stock[v.id] && qty[v.id] !== "" && qty[v.id] !== undefined && count(qty[v.id]) !== onHand(v.id));
  // Extra units join the latest delivery at its cost; with no delivery yet, they are costed at the buying price typed here.
  const adjustQuantity = async (variant) => {
    const context = stock[variant.id];
    let delta = count(qty[variant.id]) - onHand(variant.id);
    const post = (shelfId, before, after) => api("/api/v1/inventory/adjustments/", {
      method: "POST",
      body: JSON.stringify({
        variant_id: variant.id, shelf_id: shelfId, expected_quantity: String(before), counted_quantity: String(after),
        reason: quantityReason, notes: why, confirmed: true, idempotency_key: crypto.randomUUID(),
        ...(context.latest_lot_id ? { lot_id: context.latest_lot_id } : { new_lot_unit_cost: bp[variant.id] || null }),
      }),
    });
    if (delta > 0) {
      const shelf = context.locations.find((l) => l.shelf_id === context.default_shelf_id);
      return post(context.default_shelf_id, count(shelf?.quantity), count(shelf?.quantity) + delta);
    }
    for (const location of context.locations) {
      const take = Math.min(-delta, count(location.quantity) - count(location.reserved));
      if (take <= 0) continue;
      await post(location.shelf_id, count(location.quantity), count(location.quantity) - take);
      delta += take;
      if (!delta) return;
    }
    if (delta) throw new Error("Some of this stock is set aside for customers, so the quantity cannot go that low.");
  };
  useEffect(() => {
    if (focusVariantId) document.getElementById(`variant-${focusVariantId}`)?.scrollIntoView?.({ block: "start" });
  }, [focusVariantId]);
  // Only products entered by mistake (nothing sold, received or moved) can be deleted; the server decides.
  const remove = async () => {
    setError("");
    try {
      const check = await api(`/api/v1/catalog/products/${data.id}/can-delete/`);
      if (!check.can_delete) {
        setError(`${data.name} can't be deleted because ${check.reason}. Untick Active and save to hide it instead.`);
        return;
      }
      if (!(await confirmAction({ title: `Delete ${data.name}?`, text: "The product and any opening stock entered with it are removed, and that stock value is taken out of the books. This cannot be undone.", confirmButtonText: "Delete product" }))) return;
      setSaving(true);
      await api(`/api/v1/catalog/products/${data.id}/`, { method: "DELETE" });
      (onDeleted || onSaved)();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const save = async (e) => {
    e.preventDefault();
    for (const variant of canVariant ? variants : []) {
      const fields = variantFields(variant, isService);
      const bad = changed(variant, original(variant.id), fields) && badNumber(variant, fields);
      if (bad) {
        setError(`${multiple ? `${variant.name || "Standard"}: ` : ""}${labels[bad]} must be a number. Type digits only (0 is a zero, not the letter O); use 0 for none.`);
        return;
      }
    }
    if (changedBp.length || changedQty.length) {
      const name = (v) => (multiple ? `${v.name}: ` : "");
      const lines = [
        ...changedBp.map((v) => `${name(v)}buying price ${businessCurrency()} ${count(latestLot[v.id].buying_price)} → ${businessCurrency()} ${count(bp[v.id])}`),
        ...changedQty.map((v) => `${name(v)}quantity ${onHand(v.id)} → ${count(qty[v.id])}`),
      ];
      if (!(await confirmAction({ title: "Save these changes?", text: `${lines.join("; ")}.`, confirmButtonText: "Save changes" }))) return;
    }
    setSaving(true);
    setError("");
    let step = data.name;
    try {
      if (canProduct) await api(`/api/v1/catalog/products/${data.id}/`, { method: "PATCH", body: JSON.stringify(payload(data, productFields)) });
      if (canVariant)
        for (const variant of variants) {
          const fields = variantFields(variant, isService);
          if (!changed(variant, original(variant.id), fields)) continue;
          step = `${data.name} (${variant.name || "Standard"})`;
          await api(`/api/v1/catalog/variants/${variant.id}/`, { method: "PATCH", body: JSON.stringify(payload(variant, fields)) });
        }
      for (const variant of changedBp) {
        step = `Buying price of ${variant.name}`;
        await api(`/api/v1/inventory/lots/${latestLot[variant.id].id}/cost/`, { method: "POST", body: JSON.stringify({ unit_cost: bp[variant.id], reason: why }) });
      }
      for (const variant of changedQty) {
        step = `Quantity of ${variant.name}`;
        await adjustQuantity(variant);
      }
      onSaved();
    } catch (err) {
      setError(`${step}: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };
  const input = (field, row, set, id) => {
    const value = row[field];
    if (field === "category" || field === "brand")
      return (
        <select id={id} value={value || ""} onChange={(e) => set(e.target.value)}>
          {field === "brand" && <option value="">No brand</option>}
          {(field === "brand" ? brands : categories).map((option) => (
            <option key={option.id} value={option.id}>{option.name}</option>
          ))}
        </select>
      );
    if (field === "product_type")
      return (
        <select id={id} value={value || "STOCK_ITEM"} onChange={(e) => set(e.target.value)}>
          <option value="STOCK_ITEM">Stock item</option>
          <option value="SERVICE">Billable service</option>
        </select>
      );
    if (field === "description") return <textarea id={id} value={value ?? ""} onChange={(e) => set(e.target.value)} />;
    if (checkboxes.includes(field)) return <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => set(e.target.checked)} />;
    return <input id={id} type={numeric.includes(field) ? "number" : "text"} min="0" step="any" value={value ?? ""} onChange={(e) => set(e.target.value)} />;
  };
  return (
    <article className="panel productEditor">
      <button type="button" className="pageBackLink" onClick={onClose}>← Back</button>
      <h2>Edit product details — {product.name}</h2>
      <form onSubmit={save}>
        <fieldset disabled={!canProduct || saving}>
          <legend>Product</legend>
          {productFields.map((field) => (
            <label key={field}>
              {labels[field]}
              {input(field, data, (value) => setData({ ...data, [field]: value }))}
            </label>
          ))}
        </fieldset>
        {variants.map((variant) => (
          <fieldset key={variant.id} id={`variant-${variant.id}`} disabled={!canVariant || saving}
            aria-label={multiple ? `Variant ${variant.name}` : "Price, codes and stock levels"}>
            <legend>{multiple ? `Variant: ${original(variant.id)?.name || variant.name}` : "Price, codes and stock levels"}</legend>
            {variantFields(variant, isService).map((field) => (
              <label key={field}>
                {labels[field === "name" ? "variant_name" : field]}
                {input(field, variant, (value) => setVariants((rows) => rows.map((r) => (r.id === variant.id ? { ...r, [field]: value } : r))))}
              </label>
            ))}
            {!isService && canSeeCost && variant.id in latestLot && (
              <label>
                Buying price (BP)
                <input type="number" min="0.01" step="0.01" placeholder="Not recorded" disabled={latestLot[variant.id] ? !latestLot[variant.id].can_correct : false}
                  value={bp[variant.id] ?? ""} onChange={(e) => setBp({ ...bp, [variant.id]: e.target.value })} />
                {!latestLot[variant.id] && <small className="muted">No stock received yet: this is the cost of the stock you add below.</small>}
              </label>
            )}
            {!isService && canAdjust && stock[variant.id] && (
              <label>
                Quantity in stock
                <input type="number" min="0" step="any" value={qty[variant.id] ?? ""} onChange={(e) => setQty({ ...qty, [variant.id]: e.target.value })} />
              </label>
            )}
          </fieldset>
        ))}
        {changedQty.length > 0 && (
          <label>
            Why is the quantity changing?
            <select value={quantityReason} onChange={(e) => setQuantityReason(e.target.value)}>
              {QUANTITY_REASONS.map((reason) => <option key={reason}>{reason}</option>)}
            </select>
          </label>
        )}
        {(changedBp.length > 0 || changedQty.length > 0) && (
          <label>
            Note (what happened)
            <input required={changedBp.length > 0} maxLength="200" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. typed 150 instead of 1500" />
          </label>
        )}
        <button disabled={saving}>Save changes</button>
        <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        <FormError title="Could not save everything." message={error} />
      </form>
      {canProduct && <ProductPhotos embedded product={product} canCreateVariant={hasPermission(user, "catalog.add_productvariant")} onSaved={() => onRefresh?.()} />}
      {canProduct && <div className="dangerZone">
        <p>Delete a product entered by mistake. Products that were sold or received can't be deleted — untick Active instead.</p>
        <button type="button" className="danger" disabled={saving} onClick={remove}>Delete product</button>
      </div>}
    </article>
  );
}
