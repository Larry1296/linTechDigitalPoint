import { useState } from "react";
import { FormField } from "../../../components/forms/FormField";
import { findSkuCompartment, suggestProductSku } from "../sku";

export function ProductSkuField({
  productName,
  variantName,
  zones,
  shelfId,
  productType = "STOCK_ITEM",
}) {
  const [customSku, setCustomSku] = useState(null);
  const compartment = findSkuCompartment(zones, shelfId);
  const suggestion = suggestProductSku({
    productName,
    variantName,
    compartmentCode: compartment?.code,
    productType,
  });
  return (
    <div>
      <FormField
        label={productType === "SERVICE" ? "Service code" : "SKU"}
        name="sku"
        required
        maxLength={64}
        value={customSku ?? suggestion}
        onChange={(event) => setCustomSku(event.target.value)}
      />
      {customSku !== null && (
        <button
          type="button"
          className="secondary"
          onClick={() => setCustomSku(null)}
        >
          Use suggested SKU
        </button>
      )}
      {productType === "STOCK_ITEM" && !compartment && (
        <small className="muted">
          Select an exact compartment to include its rack, level and shelf in
          the SKU.
        </small>
      )}
    </div>
  );
}
