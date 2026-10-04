import { categoryUsable } from "./categories";

// The value most products here share, or "" when there are none. With `unanimous`, only a value every product shares.
function common(values, unanimous = false) {
  const present = values.filter((v) => v !== null && v !== undefined && v !== "");
  if (!present.length || (unanimous && present.length !== values.length)) return "";
  const tally = new Map();
  present.forEach((v) => tally.set(String(v), (tally.get(String(v)) || 0) + 1));
  const [top, n] = [...tally].sort((a, b) => b[1] - a[1])[0];
  return unanimous && n !== values.length ? "" : top;
}

/** What a new product added while browsing a category most likely has, taken from the products already filed there:
 * the category itself, then the product type, stock levels and usual shelf most of them use, and the brand only when
 * every one of them is that brand. Names, codes and prices are never guessed. */
export function categoryDefaults(category, products = []) {
  if (!category || category.id === "other") return {};
  const variants = products.flatMap((p) => p.variants || []);
  const shelves = products.flatMap((p) => (p.locations || []).map((l) => l.preferred_shelf?.id));
  const defaults = {
    category: categoryUsable(category) ? String(category.id) : "",
    categoryName: category.name,
    product_type: common(products.map((p) => p.product_type)) || "STOCK_ITEM",
    brand: common(products.map((p) => p.brand), true),
    minimum_stock: common(variants.map((v) => Number(v.minimum_stock))),
    target_stock: common(variants.map((v) => Number(v.target_stock))),
    shelf: common(shelves),
  };
  return defaults;
}
