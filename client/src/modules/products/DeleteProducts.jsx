import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { FormError } from "../../components/forms/FormNotice";

// Which products are ticked on the list, and how to open the delete prompt for some of them.
export const ProductSelection = createContext(null);
export const useProductSelection = () => useContext(ProductSelection);

const count = (value) => Number(value || 0).toLocaleString();

// Asks how to delete: keep the records (hidden everywhere) or remove permanently, which is only possible
// for products that were never sold or received. The server checks each product and says why.
export function DeleteProductsDialog({ ids, canHide, canRemove, onClose, onDone }) {
  const [rows, setRows] = useState(null);
  const [mode, setMode] = useState("hide");
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/v1/catalog/products/delete-check/", { method: "POST", body: JSON.stringify({ ids }) })
      .then((data) => { setRows(data); setMode(canHide ? "hide" : "remove"); })
      .catch((err) => setError(err.message));
  }, [ids, canHide]);
  const removable = (rows || []).filter((row) => row.can_remove);
  const kept = (rows || []).filter((row) => !row.can_remove);
  const withStock = (rows || []).filter((row) => Number(row.on_shelf) > 0);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const results = await api("/api/v1/catalog/products/bulk-delete/", { method: "POST",
        body: JSON.stringify({ ids, mode, hide_rest: mode === "remove" && kept.length > 0 }) });
      onDone(results);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  const one = ids.length === 1;
  return (
    <div className="shelfOverlay" role="presentation" onMouseDown={onClose}>
      <form className="shelfPanel deleteProducts" role="dialog" aria-modal="true" aria-labelledby="delete-products-title"
        onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => void submit(event)}>
        <h2 id="delete-products-title">Delete {one ? (rows?.[0]?.name || "this product") : `${ids.length} products`}?</h2>
        {!rows ? (error ? null : <p>Checking…</p>) : <>
          <ul className="deleteProductList">{rows.map((row) => (
            <li key={row.id}>
              <b>{row.name}</b>
              <small className={row.can_remove ? "muted" : undefined}>{row.can_remove ? "Nothing sold or received yet: can be removed permanently."
                : `Its records must be kept: ${row.reason}.`}{Number(row.on_shelf) > 0 ? ` ${count(row.on_shelf)} still on the shelf.` : ""}</small>
            </li>
          ))}</ul>
          <fieldset className="deleteChoice" disabled={busy}>
            <legend>How do you want to delete {one ? "it" : "them"}?</legend>
            {canHide && <label className="deleteOption">
              <input type="radio" name="mode" value="hide" checked={mode === "hide"} onChange={() => setMode("hide")} />
              <span><b>Delete, but keep the records</b>
                <small>Hidden from the till, product list and stock check. Past sales and history stay, and it can be brought back later.</small></span>
            </label>}
            {canRemove && <label className={`deleteOption${removable.length ? "" : " disabled"}`}>
              <input type="radio" name="mode" value="remove" checked={mode === "remove"} disabled={!removable.length} onChange={() => setMode("remove")} />
              <span><b>Remove permanently</b>
                <small>{!removable.length ? "Not possible for these: sales and deliveries must be kept (the books cannot be erased, and KRA requires records for 5 years)."
                  : kept.length ? `${removable.length} will be erased completely; the other ${kept.length} can only be deleted with their records kept, so they will be hidden.`
                  : "Erased completely, with the stock you entered for it. This cannot be undone."}</small></span>
            </label>}
          </fieldset>
          {withStock.length > 0 && <p className="formNotice formNoticeInfo">Stock still on the shelf stays counted in your stock value while a product is hidden.
            To take it off, count it with <a href="/admin/stock-check">Stock check</a> first.</p>}
          {mode === "remove" && removable.length > 0 && <label className="deleteSure"><input type="checkbox" checked={sure} onChange={(event) => setSure(event.target.checked)} />
            I understand this cannot be undone.</label>}
        </>}
        <div className="actionRow">
          <button className="danger" disabled={busy || !rows || (mode === "remove" && !sure)}>{mode === "remove" ? "Remove permanently" : "Delete, keep records"}</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
        <FormError title="Could not delete." message={error} />
      </form>
    </div>
  );
}
