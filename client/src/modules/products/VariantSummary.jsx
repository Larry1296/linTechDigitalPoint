import { businessCurrency } from "../../core/organization/presentation";
export const hasPermission = (user, permission) =>
  Boolean(user?.is_superuser || user?.permissions?.includes(permission));
export const stockLimit = (p) =>
  p.product_type === "SERVICE" ? Infinity : Math.max(0, Number(p.available));
export function VariantSummary({ row }) {
  return (
    <span className="productSearchDetails">
      <strong>
        {row.product_name} — {row.variant_name}
      </strong>
      <span>
        {row.category_name} · {row.sku}
      </span>
      <span>
        BP {businessCurrency()} {row.buying_price ?? "—"} · SP {businessCurrency()} {row.selling_price}
        {row.available !== undefined &&
          ` · ${stockLimit(row) === 0 ? "Out of stock" : row.product_type === "SERVICE" ? "Service" : `${row.available} available`}`}
      </span>
      {row.locations?.map((l, i) => (
        <small key={i}>
          {l.zone} → {l.shelf_code} — {l.shelf_name}
        </small>
      ))}
    </span>
  );
}
