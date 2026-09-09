import { Link } from "react-router-dom";
import { ProductImage } from "./ProductImage";
import { StockAvailability } from "./StockAvailability";
import { AddToCartButton } from "./AddToCartButton";

export function ProductCard({ product, onAdd }) {
  const Heading = onAdd ? "h2" : "h3";
  const viewLink = (
    <Link
      className={`button${onAdd ? " secondary" : ""}`}
      to={`/products/${product.id}`}
    >
      {product.variant_count > 1 ? "Choose variant" : onAdd ? "View" : "View product"}
    </Link>
  );
  return (
    <article className="productCard">
      <ProductImage product={product} />
      {onAdd && <small>{product.category}</small>}
      <Heading>{product.display_name}</Heading>
      <b>KSh {product.selling_price}</b>
      <StockAvailability
        available={product.available}
        showLowStock={Boolean(onAdd)}
      />
      {onAdd ? (
        <div className="cardActions">
          {viewLink}
          {product.variant_count > 1 ? null : <AddToCartButton product={product} onAdd={onAdd} />}
        </div>
      ) : (
        viewLink
      )}
    </article>
  );
}
