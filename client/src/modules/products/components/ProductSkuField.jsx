import { useState } from "react";
import { FormField } from "../../../components/forms/FormField";
import { suggestProductSku } from "../sku";

export function ProductSkuField({
  productName,
  brandName = "",
  variantName,
  productType = "STOCK_ITEM",
}) {
  const [customSku, setCustomSku] = useState(null);
  const suggestion = suggestProductSku({
    productName,
    brandName,
    variantName,
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
    </div>
  );
}
