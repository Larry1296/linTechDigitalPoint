import { DisplayImageInput } from "../products/components/DisplayImageInput";
import { ProductSkuField } from "../products/components/ProductSkuField";
import { FormField } from "../../components/forms/FormField";
import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { useAuth } from "../../core/auth/AuthContext";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";

const emptyLine = () => ({
  variant_id: "",
  received_quantity: "",
  unit_cost: "",
  update_selling_price: false,
  new_selling_price: "",
  placements: [{ shelf_id: "", quantity: "" }],
});
export function ReceivePage() {
  const { user } = useAuth();
  const [draftKey] = useState(() => `receipt-draft:${user.id}`);
  const [draft] = useState(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(draftKey));
      return saved?.version === 1 &&
        Array.isArray(saved.lines) &&
        saved.lines.length &&
        saved.details
        ? saved
        : {};
    } catch {
      return {};
    }
  });
  const [idempotencyKey, setIdempotencyKey] = useState(
    () => draft.idempotencyKey || crypto.randomUUID(),
  );
  const [variants, setVariants] = useState([]);
  const [categories, setCategories] = useState([]);
  const [zones, setZones] = useState([]);
  const [locationsLoaded, setLocationsLoaded] = useState(false);
  const [categoryId, setCategoryId] = useState(draft.categoryId || "");
  const [query, setQuery] = useState(draft.query || "");
  const [lines, setLines] = useState(draft.lines || [{...emptyLine(), variant_id: new URLSearchParams(window.location.search).get("variant") || ""}]);
  const [details, setDetails] = useState(
    draft.details || {
      supplier_name: "",
      external_reference: "",
      received_at: new Date().toISOString().slice(0, 16),
      notes: "",
    },
  );
  const [step, setStep] = useState(draft.step || 1);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(null);
  const [draftError, setDraftError] = useState("");
  useLayoutEffect(() => {
    try {
      if (success) sessionStorage.removeItem(draftKey);
      else
        sessionStorage.setItem(
          draftKey,
          JSON.stringify({
            version: 1,
            categoryId,
            query,
            lines,
            details,
            step,
            idempotencyKey,
          }),
        );
    } catch {
      setDraftError(
        "Your browser could not save the receipt draft. Keep a copy of your entries before leaving this page.",
      );
    }
  }, [
    draftKey,
    categoryId,
    query,
    lines,
    details,
    step,
    idempotencyKey,
    success,
  ]);
  const [creating, setCreating] = useState(false);
  const [displayImage, setDisplayImage] = useState(null);
  const [imageError, setImageError] = useState("");
  const [newProductOpen, setNewProductOpen] = useState(false);
  const [newProductName, setNewProductName] = useState("");
  const [newVariantName, setNewVariantName] = useState("Standard");
  const [newProductShelf, setNewProductShelf] = useState("");
  const [newProductCategory, setNewProductCategory] = useState("");
  const newProductZones = zones
    .map((zone) => ({
      ...zone,
      stacks: (zone.stacks || []).filter((stack) =>
        (stack.categories || []).some(
          (category) => String(category.id) === newProductCategory,
        ),
      ),
    }))
    .filter((zone) => zone.stacks.length);
  const [newProductLine, setNewProductLine] = useState(null);
  const [savingProduct, setSavingProduct] = useState(false);
  useEffect(() => {
    void Promise.all([
      api("/api/v1/inventory/variants/search/"),
      api("/api/v1/locations/zones/"),
      api("/api/v1/inventory/categories/available/"),
    ])
      .then(([items, locationData, categoryData]) => {
        setVariants(items);
        setZones(locationData);
        setLocationsLoaded(true);
        setCategories(categoryData);
      })
      .catch((err) => setError(err.message));
  }, []);
  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    return variants
      .filter(
        (item) =>
          (!categoryId || item.category_id === Number(categoryId)) &&
          (!q ||
            [
              item.product_name,
              item.variant_name,
              item.sku,
              item.barcode,
              item.brand,
              item.category,
            ].some((value) =>
              String(value || "")
                .toLowerCase()
                .includes(q),
            )),
      )
      .slice(0, 20);
  }, [variants, query, categoryId]);
  const eligibleZones = useMemo(
    () =>
      zones
        .map((zone) => ({
          ...zone,
          stacks: (zone.stacks || []).filter(
            (stack) =>
              !categoryId ||
              (stack.categories || []).some(
                (category) => category.id === Number(categoryId),
              ),
          ),
        }))
        .filter((zone) => zone.stacks.length),
    [zones, categoryId],
  );
  const totalUnits = lines.reduce(
    (sum, line) => sum + Number(line.received_quantity || 0),
    0,
  );
  const totalCost = lines.reduce(
    (sum, line) =>
      sum + Number(line.received_quantity || 0) * Number(line.unit_cost || 0),
    0,
  );
  const updateLine = (index, patch) =>
    setLines((old) =>
      old.map((line, i) => (i === index ? { ...line, ...patch } : line)),
    );
  const validate = () => {
    for (const [index, line] of lines.entries()) {
      const placements = line.placements.reduce(
        (sum, item) => sum + Number(item.quantity || 0),
        0,
      );
      if (
        !line.variant_id ||
        Number(line.received_quantity) <= 0 ||
        Number(line.unit_cost) < 0
      )
        return `Line ${index + 1}: choose a variant and enter a positive quantity and buying price.`;
      if (placements !== Number(line.received_quantity))
        return `Line ${index + 1}: placement quantities must equal the received quantity.`;
      if (
        line.placements.some(
          (item) => !item.shelf_id || Number(item.quantity) <= 0,
        )
      )
        return `Line ${index + 1}: complete every compartment placement.`;
      if (line.update_selling_price && line.new_selling_price === "")
        return `Line ${index + 1}: enter the new selling price.`;
    }
    return "";
  };
  const submit = async () => {
    const validation = validate();
    if (validation) {
      setError(validation);
      return;
    }
    if (
      !(await confirmAction({
        title: "Complete this receipt?",
        text: "This creates real inventory lots, balances, and purchase movements.",
        confirmButtonText: "Complete receipt",
      }))
    )
      return;
    setError("");
    setCreating(true);
    try {
      const result = await api("/api/v1/inventory/receipts/", {
        method: "POST",
        body: JSON.stringify({
          ...details,
          idempotency_key: idempotencyKey,
          lines: lines.map((line) => ({
            ...line,
            received_quantity: line.received_quantity,
            placements: line.placements.map(({ shelf_id, quantity }) => ({
              shelf_id,
              quantity,
            })),
          })),
        }),
      });
      setSuccess(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };
  const goToStep = (nextStep) => {
    if (creating || savingProduct) return;
    if (nextStep > 1 && !categoryId) {
      setError("Choose a merchandise category before continuing to items.");
      return;
    }
    if (nextStep === 3) {
      const validation = validate();
      if (validation) {
        setError(validation);
        return;
      }
    }
    setError("");
    setStep(nextStep);
  };
  if (success)
    return (
      <section className="successCard">
        <span className="eyebrow">Receipt completed</span>
        <h1>{success.receipt_number}</h1>
        <p>
          {success.lines.length} product lines received ·{" "}
          {success.lines.reduce((s, l) => s + Number(l.quantity), 0)} units ·
          KSh{" "}
          {success.lines
            .reduce((s, l) => s + Number(l.line_cost), 0)
            .toFixed(2)}
        </p>
        <button
          onClick={() => {
            setSuccess(null);
            setLines([emptyLine()]);
            setIdempotencyKey(crypto.randomUUID());
            setStep(1);
          }}
        >
          Receive another delivery
        </button>
        <button className="secondary" onClick={() => window.print()}>
          Print receipt
        </button>
      </section>
    );
  return (
    <section className="receiveWorkflow">
      <span className="eyebrow">Purchasing and exact placement</span>
      <h1>Receive stock</h1>
      {draftError && (
        <p role="alert" className="formError">
          {draftError}
        </p>
      )}
      <nav className="workflowSteps" aria-label="Receipt steps">
        {["Receipt details", "Items and placement", "Review"].map(
          (label, index) => (
            <button
              key={label}
              type="button"
              className={step === index + 1 ? "active" : ""}
              aria-current={step === index + 1 ? "step" : undefined}
              disabled={creating || savingProduct}
              onClick={() => goToStep(index + 1)}
            >
              {index + 1}. {label}
            </button>
          ),
        )}
      </nav>
      {error && <p className="formError">{error}</p>}
      {step === 1 && (
        <div className="formCard wide">
          {!categories.length && (
            <div className="callout">
              <div>
                <b>No rack merchandise categories are configured yet.</b>
                <p>
                  Open Digital Shop, edit each rack, and assign its primary or
                  additional merchandise categories before receiving stock.
                </p>
              </div>
              <a className="button" href="/admin-app/digital-shop">
                Configure rack categories
              </a>
            </div>
          )}
          <label>
            Merchandise category from configured racks
            <select
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              required
            >
              <option value="">
                Choose a category assigned to an active rack
              </option>
              {categories.map((category) => (
                <option value={category.id} key={category.id}>
                  {category.name} — available in{" "}
                  {category.rack_names.join(", ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Supplier name
            <input
              value={details.supplier_name}
              onChange={(e) =>
                setDetails({ ...details, supplier_name: e.target.value })
              }
              required
            />
          </label>
          <label>
            Supplier invoice / delivery note (optional)
            <input
              value={details.external_reference}
              onChange={(e) =>
                setDetails({ ...details, external_reference: e.target.value })
              }
            />
          </label>
          <label>
            Date received
            <input
              type="datetime-local"
              value={details.received_at}
              onChange={(e) =>
                setDetails({ ...details, received_at: e.target.value })
              }
              required
            />
          </label>
          <label>
            General notes
            <textarea
              value={details.notes}
              onChange={(e) =>
                setDetails({ ...details, notes: e.target.value })
              }
            />
          </label>
          <button onClick={() => goToStep(2)} disabled={!categoryId}>
            Continue to items
          </button>
        </div>
      )}
      {step === 2 && (
        <div className="receiveLines">
          {lines.map((line, index) => {
            const selected = variants.find(
              (item) => item.id === Number(line.variant_id),
            );
            return (
              <article className="formCard receiptLine" key={index}>
                <div className="heading">
                  <h2>Product line {index + 1}</h2>
                  {lines.length > 1 && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        setLines(lines.filter((_, i) => i !== index))
                      }
                    >
                      Remove
                    </button>
                  )}
                </div>
                <label>
                  Search product, SKU, barcode, brand or category
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search stock items"
                  />
                </label>
                <label>
                  Product variant
                  <select
                    value={line.variant_id}
                    onChange={(e) =>
                      updateLine(index, { variant_id: e.target.value })
                    }
                    required
                  >
                    <option value="">Choose a variant</option>
                    {(selected &&
                    !filtered.some((item) => item.id === selected.id)
                      ? [selected, ...filtered]
                      : filtered
                    ).map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.product_name} — {item.variant_name} · {item.sku} ·
                        KSh {item.selling_price}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setNewProductLine(index);
                    if (newProductLine === null) {
                      setNewProductName("");
                      setNewVariantName("Standard");
                      setNewProductCategory(categoryId);
                      setNewProductShelf(line.placements[0]?.shelf_id || "");
                    }
                    setNewProductOpen(true);
                  }}
                >
                  + Create new product
                </button>
                {selected && (
                  <p className="muted">
                    Current selling price: KSh {selected.selling_price}
                  </p>
                )}
                <div className="formGrid">
                  <label>
                    Received quantity
                    <input
                      type="number"
                      min=".001"
                      step=".001"
                      value={line.received_quantity}
                      onChange={(e) =>
                        updateLine(index, { received_quantity: e.target.value })
                      }
                      required
                    />
                  </label>
                  <label>
                    Buying price per unit
                    <input
                      type="number"
                      min="0"
                      step=".01"
                      value={line.unit_cost}
                      onChange={(e) =>
                        updateLine(index, { unit_cost: e.target.value })
                      }
                      required
                    />
                  </label>
                </div>
                <label className="checkboxRow">
                  <input
                    type="checkbox"
                    checked={line.update_selling_price}
                    onChange={(e) =>
                      updateLine(index, {
                        update_selling_price: e.target.checked,
                      })
                    }
                  />{" "}
                  Update selling price
                </label>
                {line.update_selling_price && (
                  <label>
                    New selling price
                    <input
                      type="number"
                      min="0"
                      step=".01"
                      value={line.new_selling_price}
                      onChange={(e) =>
                        updateLine(index, { new_selling_price: e.target.value })
                      }
                      required
                    />
                  </label>
                )}
                <h3>Exact placement</h3>
                {line.placements.map((placement, pindex) => (
                  <div className="placementRow" key={pindex}>
                    {locationsLoaded && (
                      <PhysicalLocationPicker
                        zones={eligibleZones}
                        value={
                          placement.shelf_id ? Number(placement.shelf_id) : ""
                        }
                        required
                        onChange={(shelf_id) =>
                          updateLine(index, {
                            placements: line.placements.map((item, i) =>
                              i === pindex ? { ...item, shelf_id } : item,
                            ),
                          })
                        }
                      />
                    )}
                    <label>
                      Quantity
                      <input
                        type="number"
                        min=".001"
                        step=".001"
                        value={placement.quantity}
                        onChange={(e) =>
                          updateLine(index, {
                            placements: line.placements.map((item, i) =>
                              i === pindex
                                ? { ...item, quantity: e.target.value }
                                : item,
                            ),
                          })
                        }
                        required
                      />
                    </label>
                    {line.placements.length > 1 && (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() =>
                          updateLine(index, {
                            placements: line.placements.filter(
                              (_, i) => i !== pindex,
                            ),
                          })
                        }
                      >
                        Remove placement
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    updateLine(index, {
                      placements: [
                        ...line.placements,
                        { shelf_id: "", quantity: "" },
                      ],
                    })
                  }
                >
                  Split across another compartment
                </button>
              </article>
            );
          })}
          <button
            type="button"
            className="secondary"
            onClick={() => setLines([...lines, emptyLine()])}
          >
            Add another product line
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => goToStep(1)}
          >
            Back to receipt details
          </button>
          <button onClick={() => goToStep(3)}>Review receipt</button>
        </div>
      )}
      {step === 3 && (
        <div className="formCard wide reviewCard">
          <h2>Review and confirm</h2>
          <p>
            <b>Supplier:</b> {details.supplier_name} · <b>Reference:</b>{" "}
            {details.external_reference || "System generated"}
          </p>
          {lines.map((line, index) => {
            const product = variants.find(
              (item) => item.id === Number(line.variant_id),
            );
            return (
              <div className="reviewLine" key={index}>
                <b>
                  {product?.product_name} — {product?.variant_name}
                </b>
                <span>
                  {line.received_quantity} units · KSh {line.unit_cost} each ·
                  line cost KSh{" "}
                  {(
                    Number(line.received_quantity) * Number(line.unit_cost)
                  ).toFixed(2)}
                </span>
                <small>
                  {line.placements
                    .map((p) => `${p.quantity} at shelf ${p.shelf_id}`)
                    .join(" · ")}
                </small>
              </div>
            );
          })}
          <strong>
            Total: {totalUnits} units · KSh {totalCost.toFixed(2)}
          </strong>
          <button onClick={submit} disabled={creating}>
            {creating ? "Saving…" : "Complete receipt"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={creating}
            onClick={() => goToStep(2)}
          >
            Back to edit
          </button>
        </div>
      )}
      {creating && <p className="muted">Saving receipt…</p>}
      {newProductLine !== null && (
        <div
          className="modalBackdrop"
          style={newProductOpen ? undefined : { display: "none" }}
        >
          <form
            className="formCard modalCard"
            onSubmit={async (event) => {
              event.preventDefault();
              if (savingProduct) return;
              try {
                if (!displayImage) {
                  setImageError(
                    "Add a Product display image before making this product visible to customers.",
                  );
                  return;
                }
                const data = new FormData(event.currentTarget);
                setSavingProduct(true);
                data.set("display_image", displayImage);
                data.set("ecommerce_visible", "true");
                data.set("online_orderable", "true");
                const result = await api(
                  "/api/v1/catalog/products/create-inline/",
                  {
                    method: "POST",
                    body: data,
                  },
                );
                const fresh = await api(
                  `/api/v1/inventory/variants/search/?q=${encodeURIComponent(data.get("sku"))}`,
                );
                setVariants((old) => [
                  ...old,
                  ...fresh.filter(
                    (item) => !old.some((existing) => existing.id === item.id),
                  ),
                ]);
                updateLine(newProductLine, {
                  variant_id: String(result.variant_id),
                  placements: lines[newProductLine].placements.map(
                    (placement, index) =>
                      index === 0
                        ? { ...placement, shelf_id: newProductShelf }
                        : placement,
                  ),
                });
                setNewProductOpen(false);
                setNewProductLine(null);
                setDisplayImage(null);
                setImageError("");
              } catch (err) {
                setImageError(err.message);
              } finally {
                setSavingProduct(false);
              }
            }}
          >
            <h2>Create product</h2>
            {imageError && <p role="alert">{imageError}</p>}
            <DisplayImageInput
              file={displayImage}
              onChange={(file) => {
                setDisplayImage(file);
                setImageError("");
              }}
              required
            />
            <FormField
              label="Product name"
              name="name"
              required
              value={newProductName}
              onChange={(event) => setNewProductName(event.target.value)}
            />
            <label>
              Category
              <select
                name="category_id"
                required
                value={newProductCategory}
                onChange={(event) => {
                  setNewProductCategory(event.target.value);
                  setNewProductShelf("");
                }}
              >
                <option value="">Choose category</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>
            <FormField
              label="Variant name"
              name="variant_name"
              value={newVariantName}
              onChange={(event) => setNewVariantName(event.target.value)}
              required
            />
            <PhysicalLocationPicker
              zones={newProductZones}
              value={newProductShelf}
              onChange={setNewProductShelf}
              required
            />
            <ProductSkuField
              productName={newProductName}
              variantName={newVariantName}
              zones={newProductZones}
              shelfId={newProductShelf}
            />
            <FormField label="Barcode" name="barcode" />
            <FormField
              label="Selling price"
              name="selling_price"
              type="number"
              min="0"
              step=".01"
              required
            />
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
            <button disabled={savingProduct}>
              {savingProduct
                ? "Creating product…"
                : "Create and return to receipt"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={savingProduct}
              onClick={() => {
                setNewProductOpen(false);
                setImageError("");
              }}
            >
              Back to receipt
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
