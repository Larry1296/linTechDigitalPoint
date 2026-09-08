export function StockAvailability({
  available,
  showLowStock = true,
  as: Tag = "span",
}) {
  const inStock = available === null || Number(available) > 0;
  const label =
    available === null
      ? "Available"
      : !inStock
        ? "Out of stock"
        : showLowStock && Number(available) <= 3
          ? `Only ${Number(available)} left`
          : "In stock";
  return <Tag className={inStock ? "stock" : "out"}>{label}</Tag>;
}
