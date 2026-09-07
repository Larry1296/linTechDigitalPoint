import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PhysicalLocationPicker } from "../../components/PhysicalLocationPicker";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";
export function ReceivePage() {
  const [products, setProducts] = useState([]);
  const [zones, setZones] = useState([]);
  const [placements, setPlacements] = useState([{ quantity: "" }]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([
      api("/api/v1/catalog/variants/"),
      api("/api/v1/locations/zones/"),
    ]).then(([p, z]) => {
      setProducts(
        p.filter(
          (variant) => variant.active && variant.product_type === "STOCK_ITEM",
        ),
      );
      setZones(z);
    });
  }, []);
  const submit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget));
    if (
      !(await confirmAction({
        title: "Receive this stock?",
        text: "This will add inventory to the selected shelf placements.",
        confirmButtonText: "Receive stock",
      }))
    )
      return;
    try {
      const result = await api("/api/v1/inventory/receive/", {
        method: "POST",
        body: JSON.stringify({ ...f, placements }),
      });
      setMsg(
        `Stock received into the selected physical shelf placement. Receipt ${result.reference}.`,
      );
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <>
      <span className="eyebrow">Purchasing and exact placement</span>
      <h1>Receive Stock</h1>
      {msg && <div className="success">{msg}</div>}
      {error && <p className="formError">{error}</p>}
      {!products.length && (
        <div className="callout">
          <div>
            <b>No stock products have been defined yet.</b>
            <p>
              Create the product, SKU/variant, prices, and preferred shelf
              first. Then return here to receive additional stock.
            </p>
          </div>
          <Link className="button" to="/admin-app/products">
            Create Product
          </Link>
        </div>
      )}
      {!zones.length && (
        <div className="callout">
          <div>
            <b>No physical shelves have been configured yet.</b>
            <p>
              Build the Zone → Shelf Stack → Level → Shelf layout before
              receiving stock.
            </p>
          </div>
          <Link className="button" to="/admin-app/digital-shop">
            Configure Digital Shop
          </Link>
        </div>
      )}
      <form className="formCard wide" onSubmit={submit}>
        <label>
          Product
          <select name="variant_id" required disabled={!products.length}>
            <option value="">Choose a defined product</option>
            {products.map((p) => (
              <option value={p.id} key={p.id}>
                {p.product_name} — {p.name} · {p.sku}
              </option>
            ))}
          </select>
        </label>
        <label>
          Buying price
          <input name="unit_cost" type="number" min="0" step=".01" required />
        </label>
        <label>
          Selling price
          <input
            name="selling_price"
            type="number"
            min="0"
            step=".01"
            required
          />
        </label>
        <label>
          Supplier
          <input name="supplier_name" />
        </label>
        <label>
          Supplier invoice / delivery note (optional)
          <input
            name="reference"
            placeholder="A receipt reference is generated when left blank"
          />
        </label>
        <div className="placementHeading">
          <h2>Where will this stock be placed?</h2>
          <p className="muted">
            Choose the exact shop shelf for every quantity received. This
            location is what staff use to find the item.
          </p>
        </div>
        {placements.map((placement, index) => (
          <div className="placementRow" key={index}>
            <PhysicalLocationPicker
              zones={zones}
              value={placement.shelf_id}
              onChange={(shelf_id) =>
                setPlacements((old) =>
                  old.map((item, i) =>
                    i === index ? { ...item, shelf_id } : item,
                  ),
                )
              }
            />
            <label>
              Quantity
              <input
                type="number"
                min=".001"
                step=".001"
                value={placement.quantity}
                onChange={(e) =>
                  setPlacements((old) =>
                    old.map((item, i) =>
                      i === index
                        ? { ...item, quantity: e.target.value }
                        : item,
                    ),
                  )
                }
                required
              />
            </label>
            {placements.length > 1 && (
              <button
                type="button"
                onClick={() =>
                  setPlacements((old) => old.filter((_, i) => i !== index))
                }
              >
                Remove placement
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          className="secondary"
          onClick={() => setPlacements((old) => [...old, { quantity: "" }])}
        >
          Split across another shelf
        </button>
        <button disabled={!products.length || !zones.length}>
          Receive Stock
        </button>
      </form>
    </>
  );
}
