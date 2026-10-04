import { hasPermission } from "./VariantSummary";
export function ProductActions({ row, user }) {
  if (!hasPermission(user, "catalog.view_product")) return null;
  const productUrl = `/admin/products?product=${row.product_id}&variant=${row.id}`;
  return (
    <details className="posActions">
      <summary>Product actions</summary>
      <nav aria-label={`Actions for ${row.sku}`}>
        <a href={productUrl}>View product</a>
        {hasPermission(user, "catalog.change_product") && (
          <a href={productUrl + "&edit=product"}>Edit product details</a>
        )}
        {row.product_type !== "SERVICE" && (
          <>
            {hasPermission(user, "inventory.add_stockreceipt") && (
              <a href={`/admin/receive?variant=${row.id}`}>
                Receive more stock
              </a>
            )}
            {hasPermission(user, "inventory.adjust_stock") && (
              <a href={`/admin/adjust-stock?variant=${row.id}`}>
                Adjust stock
              </a>
            )}
          </>
        )}
      </nav>
    </details>
  );
}
