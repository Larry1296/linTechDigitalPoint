const skuPart = (value) =>
  String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "");


const words = (value) => skuPart(value).split("-").filter(Boolean);
const hasDigit = (word) => /\d/.test(word);
const PLAIN_VARIANTS = new Set(["STANDARD", "DEFAULT", "NORMAL"]);

// Short product code: the first letter of each word, with sizes and models (anything with a digit) kept whole,
// e.g. "Original Normal Full Charger" → ONFC, "Power Bank 20000" → PB-20000, "C-C HEAD(45W)" → CCH-45W.
// One-word names stay readable (up to 10 letters). A brand at the start of the name is not repeated.
export function productInitials(productName, brandName = "") {
  let list = words(productName);
  const brand = words(brandName);
  if (brand.length && list.length > brand.length && brand.every((word, i) => list[i] === word)) list = list.slice(brand.length);
  if (!list.length) return "";
  if (list.length === 1) return list[0].slice(0, 10);
  const letters = list.filter((word) => !hasDigit(word)).map((word) => word[0]).join("");
  return [letters, ...list.filter(hasDigit)].filter(Boolean).join("-");
}

// Suggested SKU: BRAND-CODE-VARIANT with no word repeated, e.g. Everady · "EVERADY 2AA" · variant "EVERADY-2AA" → EVERADY-2AA,
// Oraimo · Original Normal Full Charger → ORAIMO-ONFC, Wall charger · Black → WC-BLACK. "Standard" variants add nothing.
// The shelf is not part of the code, so moving an item never makes its SKU wrong.
export function suggestProductSku({ productName, brandName = "", variantName = "Standard", productType = "STOCK_ITEM" }) {
  const code = productInitials(productName, brandName);
  if (!code) return "";
  const brand = words(brandName);
  const used = new Set([...brand, ...words(productName), ...code.split("-")]);
  const variant = words(variantName).filter((word) => !PLAIN_VARIANTS.has(word) && !used.has(word));
  const parts = [...brand, ...code.split("-"), ...variant, ...(productType === "SERVICE" ? ["SERVICE"] : [])]
    .filter((word, i, all) => i === 0 || word !== all[i - 1]);
  let result = parts.join("-");
  while (result.length > 64 && parts.length > 1) { parts.splice(parts.length - (productType === "SERVICE" ? 2 : 1), 1); result = parts.join("-"); }
  return result.slice(0, 64).replace(/-+$/g, "");
}
