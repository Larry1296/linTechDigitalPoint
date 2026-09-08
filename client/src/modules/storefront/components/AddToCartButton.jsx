export function AddToCartButton({
  product,
  onAdd,
  unavailableLabel = "Visit us for this service",
}) {
  return (
    <button
      onClick={() => void onAdd(product)}
      disabled={
        !product.online_orderable ||
        (product.available !== null && Number(product.available) <= 0)
      }
    >
      {product.online_orderable ? "Add to cart" : unavailableLabel}
    </button>
  );
}
