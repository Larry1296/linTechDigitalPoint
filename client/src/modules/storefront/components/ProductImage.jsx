export function ProductImage({ product, large = false }) {
  const image = product.images?.[0];
  return (
    <div className={`productImage${large ? " large" : ""}`}>
      {image ? (
        <img src={image.url} alt={image.alt || product.product_name} />
      ) : (
        product.product_name[0]
      )}
    </div>
  );
}
