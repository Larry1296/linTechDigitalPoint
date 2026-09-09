export function ProductImage({ product, large = false }) {
  const image = product.images?.[0];
  return (
    <div className={`productImage${large ? " large" : ""}`}>
      {image ? (
        <img src={image.url} alt={product.display_name || image.alt || product.product_name} />
      ) : (
        product.product_name[0]
      )}
    </div>
  );
}
