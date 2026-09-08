const skuPart = (value) =>
  String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

export function findSkuCompartment(zones, shelfId) {
  if (!shelfId) return null;
  for (const zone of zones || []) {
    if (!zone.active) continue;
    for (const rack of zone.stacks || []) {
      if (!rack.active) continue;
      for (const level of rack.levels || []) {
        if (!level.active) continue;
        const shelf = (level.shelves || []).find(
          (item) => item.active && String(item.id) === String(shelfId),
        );
        if (shelf) return shelf;
      }
    }
  }
  return null;
}

export function suggestProductSku({
  productName,
  variantName = "Standard",
  compartmentCode = "",
  productType = "STOCK_ITEM",
}) {
  const name = skuPart(productName);
  if (!name) return "";
  const variant = skuPart(variantName);
  const description = [name, variant !== "STANDARD" ? variant : ""]
    .filter(Boolean)
    .join("-");
  // Permanent compartment codes already contain the rack, level and shelf.
  // Preserve the entire location when shortening long product descriptions.
  const location =
    productType === "SERVICE" ? "SERVICE" : skuPart(compartmentCode);
  const budget = 64 - (location ? location.length + 1 : 0);
  const prefix = description.slice(0, budget).replace(/-+$/g, "");
  return [prefix, location].filter(Boolean).join("-");
}
