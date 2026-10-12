import { DisplayImageInput } from "./components/DisplayImageInput";
import { ProductSkuField } from "./components/ProductSkuField";
import { CategoryOptions, UnrackedHint } from "./categories";
import { NewCategoryForm } from "./NewCategoryForm";
import { FormField } from "../../components/forms/FormField";
import { useEffect, useState } from "react";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";
import { api } from "../../core/api/client";
import { FormError } from "../../components/forms/FormNotice";
import { useAuth } from "../../core/auth/AuthContext";
// `defaults` come from where the form was opened (e.g. the category being browsed); every field stays editable.
export function ProductForm({ zones, onSaved, preferredShelf, onClose, defaults = {} }) {
  const { user } = useAuth();
  // Shops that do not map shelves keep stock without a location, so the placement picker is not shown.
  const usesShelves = Boolean(user?.organization?.enabled_modules?.includes("locations"));
  const [displayImage, setDisplayImage] = useState(null);
  const [categories, setCategories] = useState([]);
  const [categoryId, setCategoryId] = useState(defaults.category || "");
  const [addingCategory, setAddingCategory] = useState(false);
  const can = (permission) => Boolean(user?.permissions?.includes(permission));
  const [brands, setBrands] = useState([]);
  const [productName, setProductName] = useState(defaults.name || "");
  const [variantName, setVariantName] = useState(defaults.variant_name || "Standard");
  // Sold one at a time, or in packs (paper 2 sheets for 5, cable clips 10 to a pack). One pack is one unit of stock and price.
  const [inPacks, setInPacks] = useState(Number(defaults.pack_size) > 1);
  const [packSize, setPackSize] = useState(Number(defaults.pack_size) > 1 ? String(defaults.pack_size) : "2");
  const [pieceName, setPieceName] = useState(defaults.piece_name || "piece");
  const [openingPieces, setOpeningPieces] = useState("0");
  const [pieceCost, setPieceCost] = useState("0");
  const size = inPacks ? Math.max(1, Math.floor(Number(packSize) || 1)) : 1;
  const pieces = (pieceName.trim() || "piece").replace(/s$/i, "") + "s";
  const packLabel = `pack of ${size} ${pieces}`;
  const choosePacks = (on, nextSize = packSize, nextPiece = pieceName) => {
    setInPacks(on);
    // Name the variant after the pack while it still has the default name, so the till and receipts say what is sold.
    if (on && (variantName === "Standard" || /^Pack of /.test(variantName)))
      setVariantName(`Pack of ${Math.max(1, Math.floor(Number(nextSize) || 1))} ${(nextPiece.trim() || "piece").replace(/s$/i, "")}s`);
    if (!on && /^Pack of /.test(variantName)) setVariantName("Standard");
  };
  const [type, setType] = useState(defaults.product_type || "STOCK_ITEM");
  const [shelf, setShelf] = useState(preferredShelf ?? (defaults.shelf ? Number(defaults.shelf) : undefined));
  const [error, setError] = useState("");
  const [brandId, setBrandId] = useState(defaults.brand || "");
  const [newBrand, setNewBrand] = useState(null);
  const [brandError, setBrandError] = useState("");
  // A brand can be added without leaving the form, so nothing typed so far is lost.
  const addBrand = async () => {
    setBrandError("");
    try {
      const brand = await api("/api/v1/catalog/brands/", { method: "POST", body: JSON.stringify({ name: newBrand }) });
      setBrands((rows) => [...rows, brand].sort((a, b) => a.name.localeCompare(b.name)));
      setBrandId(String(brand.id));
      setNewBrand(null);
    } catch (e) {
      setBrandError(e.message);
    }
  };
  // A new category is added from the form itself and chosen straight away, so nothing typed so far is lost.
  const categoryCreated = async (created) => {
    setCategories(await api("/api/v1/inventory/categories/available/"));
    setCategoryId(String(created.id));
    setAddingCategory(false);
  };
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
    const data = new FormData(e.currentTarget);
    data.set("preferred_shelf_id", type === "STOCK_ITEM" && shelf ? shelf : "");
    data.set("ecommerce_visible", "true");
    data.set("online_orderable", "true");
    if (displayImage) data.set("display_image", displayImage);
    data.set("pack_size", String(size));
    data.set("piece_name", inPacks ? pieceName.trim() : "");
    if (inPacks && type === "STOCK_ITEM") {
      // Counted in pieces here; kept as packs (e.g. 500 sheets = 250 packs of 2, 0.90 a sheet = 1.80 a pack).
      data.set("opening_quantity", String(Math.round((Number(openingPieces) || 0) / size * 1000) / 1000));
      data.set("opening_unit_cost", String(Math.round((Number(pieceCost) || 0) * size * 100) / 100));
    }
    try {
      const created = await api("/api/v1/catalog/products/create-with-stock/", {
        method: "POST",
        body: data,
      });
      onSaved(created);
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="formCard productForm" onSubmit={save}>
      {onClose && <button type="button" className="pageBackLink" onClick={onClose}>← Back</button>}
      <h2>Add Product</h2>
      {defaults.similarTo ? <p className="muted">Filled in from {defaults.similarTo}. Change what is different about the product you received (at least its name), then receive it.</p>
        : defaults.categoryName && <p className="muted">Filled in for {defaults.categoryName}, from the products already there. Change anything that doesn't fit.</p>}
      <FormField
        label="Product name"
        name="name"
        required
        value={productName}
        onChange={(event) => setProductName(event.target.value)}
      />
      <div className="categoryField">
        <label>
          Product category — what kind of item is this?
          <select name="category_id" required value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="">Choose a category</option>
            <CategoryOptions categories={categories} />
          </select>
        </label>
        {can("catalog.add_category") && !addingCategory &&
          <button type="button" className="secondary" onClick={() => setAddingCategory(true)}>New category</button>}
        {addingCategory && <NewCategoryForm categories={categories} zones={zones} usesShelves={usesShelves}
          canAssignRack={can("inventory.change_shelfstack")} onCreated={categoryCreated} onCancel={() => setAddingCategory(false)} />}
      </div>
      <UnrackedHint categories={categories} />
      <p className="muted">
        Categories organize products for stock management and internal lookup.
        Physical storage is selected separately.
      </p>
      <div className="brandField">
        <label>
          Brand
          <select name="brand_id" value={brandId} onChange={(e) => setBrandId(e.target.value)}>
            <option value="">No brand</option>
            {brands.filter((b) => b.active !== false).map((b) => (
              <option value={b.id} key={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        {newBrand === null
          ? <button type="button" className="secondary" onClick={() => setNewBrand("")}>New brand</button>
          : <div className="inlineForm">
              <label>New brand name<input value={newBrand} onChange={(e) => setNewBrand(e.target.value)} maxLength={120} placeholder="e.g. Oraimo" /></label>
              <button type="button" disabled={!newBrand.trim()} onClick={() => void addBrand()}>Add brand</button>
              <button type="button" className="secondary" onClick={() => { setNewBrand(null); setBrandError(""); }}>Cancel</button>
              <FormError title="Could not add the brand." message={brandError} />
            </div>}
      </div>
      <label>
        Description
        <textarea name="description" defaultValue={defaults.description || ""} />
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
      {type === "STOCK_ITEM" && <fieldset className="packChoice">
        <legend>How is it sold?</legend>
        <label className="checkRow"><input type="radio" name="sold_as" checked={!inPacks} onChange={() => choosePacks(false)} /> One at a time (e.g. a charger, a mouse)</label>
        <label className="checkRow"><input type="radio" name="sold_as" checked={inPacks} onChange={() => choosePacks(true)} /> In packs: several pieces for one price (e.g. paper 2 sheets for 5, cable clips 10 for 20)</label>
        {inPacks && <div className="packFields">
          <FormField label="Pieces in one pack" type="number" min="2" step="1" required value={packSize}
            onChange={(event) => { setPackSize(event.target.value); choosePacks(true, event.target.value, pieceName); }} />
          <FormField label="One piece is called" required maxLength={40} value={pieceName} placeholder="e.g. sheet, clip"
            onChange={(event) => { setPieceName(event.target.value); choosePacks(true, packSize, event.target.value); }} />
          <small className="muted">The price, the till and your stock count packs: one {packLabel}. You can still enter stock in {pieces}.</small>
        </div>}
      </fieldset>}
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
        brandName={brands.find((b) => String(b.id) === String(brandId))?.name || ""}
        variantName={variantName}
        productType={type}
      />
      {type === "STOCK_ITEM" && <FormField label="Barcode" name="barcode" />}
      <DisplayImageInput file={displayImage} onChange={setDisplayImage} />
      <FormField
        label={inPacks && type === "STOCK_ITEM" ? `Selling price for one ${packLabel}` : "Selling price"}
        name="selling_price"
        type="number"
        min="0"
        step=".01"
        defaultValue={defaults.selling_price}
        required
      />
      <FormField
        label="Lowest price (bargaining guide, optional)"
        name="minimum_price"
        type="number"
        min="0"
        step=".01"
        defaultValue={Number(defaults.minimum_price) > 0 ? defaults.minimum_price : undefined}
        placeholder="e.g. 500 — leave empty for no bargaining"
      />
      <small className="muted">A guide for bargaining. Staff can agree any price up to the selling price, even below this one, but never below what the item cost to buy; sales below it are noted for you to review.</small>
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
            label={inPacks ? "Minimum stock (packs)" : "Minimum stock"}
            name="minimum_stock"
            type="number"
            min="0"
            step=".001"
            defaultValue={defaults.minimum_stock || "0"}
          />
          <FormField
            label={inPacks ? "Target stock (packs)" : "Target stock"}
            name="target_stock"
            type="number"
            min="0"
            step=".001"
            defaultValue={defaults.target_stock || "0"}
          />
        </>
      )}
      {type === "STOCK_ITEM" && (
        <>
          {usesShelves && <PhysicalLocationPicker
            zones={zones}
            value={shelf}
            onChange={setShelf}
          />}
          {!defaults.similarTo && <fieldset className="openingStock">
            <legend>Stock you have now (optional)</legend>
            <p className="muted">Items already in your shop. They are added as stock you own, not as a new purchase, so nothing is recorded as money spent or owed to a supplier.</p>
            {inPacks ? <>
              <FormField label={`How many ${pieces} you have now`} type="number" min="0" step="1" value={openingPieces}
                onChange={(event) => setOpeningPieces(event.target.value)} />
              <FormField label={`Buying price for one ${pieces.replace(/s$/, "")}`} type="number" min="0" step=".01" value={pieceCost}
                onChange={(event) => setPieceCost(event.target.value)} />
              <small className="muted" role="status">{Number(openingPieces) > 0
                ? `= ${Math.round(Number(openingPieces) / size * 1000) / 1000} packs of ${size}${Number(pieceCost) > 0 ? `, bought at ${Math.round(Number(pieceCost) * size * 100) / 100} a pack` : ""}.`
                : `E.g. a ream of paper is 500 sheets: what you paid for the ream ÷ 500 is the price for one sheet.`}</small>
            </> : <>
            <FormField
              label="Quantity you have now"
              name="opening_quantity"
              type="number"
              min="0"
              step=".001"
              defaultValue="0"
            />
            <FormField
              label="Buying price per item"
              name="opening_unit_cost"
              type="number"
              min="0"
              step=".01"
              defaultValue="0"
            />
            <small className="muted">What you paid for one. If you do not know it, leave 0: the stock is marked cost pending and you can add the price later.</small>
            </>}
          </fieldset>}
        </>
      )}
      <button>{defaults.similarTo ? "Create and receive it" : "Create Product"}</button>
      <FormError title="Could not create the product." message={error} />
    </form>
  );
}
