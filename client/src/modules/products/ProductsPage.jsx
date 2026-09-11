import { ProductSearch } from "../storefront/components/ProductSearch";
import { ProductEditor } from "./ProductEditor";
import { VariantSummary, hasPermission } from "./VariantSummary";
import { useAuth } from "../../core/auth/AuthContext";
import { canAdjust } from "../inventory/StockAdjustmentPage";
import { useEffect, useRef, useState } from "react";
import { Empty, ErrorState, Loading } from "../../components/States";
import { api } from "../../core/api/client";
import { ProductPhotos } from "./ProductPhotos";
import { ProductForm } from "./ProductForm";
export function ProductsPage() {
  const { user } = useAuth();
  const initialParams = useRef(new URLSearchParams(window.location.search));
  const [editing, setEditing] = useState(null);
  const [selectedVariant, setSelectedVariant] = useState(null);
  const [page, setPage] = useState(1);
  const [next, setNext] = useState(false);
  const [rows, setRows] = useState();
  const [zones, setZones] = useState([]);
  const [photos, setPhotos] = useState(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const load = () => {
    setError("");
    return Promise.all([
      api(`/api/v1/catalog/products/?page=${page}`),
      api("/api/v1/locations/zones/"),
    ])
      .then(([products, locations]) => {
        const params = initialParams.current;
        if (params.get("product")) {
          api(
            `/api/v1/catalog/products/${encodeURIComponent(params.get("product"))}/`,
          )
            .then((product) => {
              setRows([product]);
              setSelectedVariant(Number(params.get("variant")));
              setNext(false);
              if (
                params.get("edit") === "product" &&
                hasPermission(user, "catalog.change_product")
              ) {
                params.delete("edit");
                setEditing({ product });
              }
            })
            .catch((e) => setError(e.message));
        } else setRows(products.results);
        setNext(Boolean(products.next));
        setZones(locations);
      })
      .catch((e) => setError(e.message));
  };
  useEffect(() => {
    void load();
  }, [page]);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!rows) return <Loading />;
  const visibleProducts = rows;
  const select = async (row) => {
    try {
      setRows([await api(`/api/v1/catalog/products/${row.product_id}/`)]);
      setSelectedVariant(row.id);
      setNext(false);
    } catch (e) {
      setError(e.message);
    }
  };
  if (editing)
    return (
      <ProductEditor
        {...editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          void load();
        }}
      />
    );
  if (photos)
    return (
      <ProductPhotos
        canCreateVariant={hasPermission(user, "catalog.add_productvariant")}
        product={photos}
        onClose={() => setPhotos(null)}
        onSaved={() => {
          setPhotos(null);
          void load();
        }}
      />
    );
  if (adding)
    return (
      <ProductForm
        zones={zones}
        onSaved={() => {
          setAdding(false);
          void load();
        }}
      />
    );
  return (
    <>
      <div className="heading">
        <div>
          <span className="eyebrow">Catalog and physical placement</span>
          <h1>Products</h1>
        </div>
        {hasPermission(user, "catalog.add_product") && (
          <button onClick={() => setAdding(true)}>Add Product</button>
        )}
      </div>
      <ProductSearch
        value={query}
        onChange={setQuery}
        endpoint="/api/v1/catalog/products/search-suggestions/"
        onSelect={select}
        onSearch={() => {}}
        exactScan
        renderResult={(row) => <VariantSummary row={row} />}
      />
      <nav aria-label="Catalogue pages">
        <button disabled={page === 1} onClick={() => setPage(page - 1)}>
          Previous
        </button>
        <button disabled={!next} onClick={() => setPage(page + 1)}>
          Next
        </button>
        <button
          onClick={() => {
            initialParams.current = new URLSearchParams();
            setQuery("");
            setSelectedVariant(null);
            void load();
          }}
        >
          Show catalogue
        </button>
      </nav>
      {visibleProducts.length ? (
        visibleProducts.map((product) => (
          <article className="panel" key={product.id}>
            <h2>{product.name}</h2>
            {hasPermission(user, "catalog.change_product") && (
              <>
                <button onClick={() => setEditing({ product })}>
                  Edit product details
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPhotos(product)}
                >
                  Edit images
                </button>
              </>
            )}
            <span>
              Category: {product.category_name || product.category}
              {product.product_type === "SERVICE"
                ? "Service — no shelf required"
                : "Stock item"}
            </span>
            {product.variants.map((variant) => {
              const location = product.locations.find(
                (item) => item.variant_id === variant.id,
              );
              return (
                <div
                  className="productLocation"
                  key={variant.id}
                  style={
                    selectedVariant === variant.id
                      ? { outline: "2px solid var(--primary, #2563eb)" }
                      : undefined
                  }
                  ref={(node) => {
                    if (node && selectedVariant === variant.id)
                      node.scrollIntoView?.({ block: "nearest" });
                  }}
                >
                  <b>
                    {variant.name} · {variant.sku} · Latest BP{" "}
                    {variant.latest_bp ?? "—"} · SP KSh {variant.selling_price}{" "}
                    · Physical {variant.physical ?? 0} · Reserved{" "}
                    {variant.reserved ?? 0} · Available {variant.available ?? 0}
                  </b>
                  {hasPermission(user, "catalog.change_productvariant") && (
                    <button onClick={() => setEditing({ product, variant })}>
                      Edit variant
                    </button>
                  )}
                  {hasPermission(user, "catalog.change_product") && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        setPhotos({ ...product, selectedVariantId: variant.id })
                      }
                    >
                      Edit images
                    </button>
                  )}
                  {hasPermission(user, "inventory.add_stockreceipt") &&
                    product.product_type !== "SERVICE" && (
                      <a href={`/admin-app/receive?variant=${variant.id}`}>
                        Receive more stock
                      </a>
                    )}
                  {canAdjust(user) && product.product_type !== "SERVICE" && (
                    <a href={`/admin-app/adjust-stock?variant=${variant.id}`}>
                      Adjust stock / Stock history
                    </a>
                  )}
                  <span>
                    {location?.preferred_shelf
                      ? `✓ Preferred: ${location.preferred_shelf.code} — ${location.preferred_shelf.display_name}`
                      : "⚠ No preferred physical shelf"}
                  </span>
                  {location?.actual.map((actual) => (
                    <small key={actual.shelf_id}>
                      Actual: {actual.shelf__zone__name} →{" "}
                      {actual.shelf__level__stack__display_name ||
                        "Unassigned stack"}{" "}
                      → Level {actual.shelf__level__level_number || "—"} →{" "}
                      {actual.shelf__code}: {actual.available} available
                    </small>
                  ))}
                </div>
              );
            })}
          </article>
        ))
      ) : (
        <Empty>
          {rows.length
            ? "No products match your search."
            : "No products yet. Create the first product and assign its real location."}
        </Empty>
      )}
    </>
  );
}
