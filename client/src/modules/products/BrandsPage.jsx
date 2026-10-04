import { useCallback, useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { ErrorState, Loading } from "../../components/States";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { useLiveRefresh } from "../../core/data/liveRefresh";

function Notice({ notice, place }) {
  if (notice?.place !== place) return null;
  return notice.kind === "error" ? <FormError title={notice.title} message={notice.text} /> : <FormSuccess message={notice.text} />;
}

// Brands label products (e.g. Oraimo, Tecno). A brand in use cannot be deleted; untick Active to hide it.
export function BrandsPage() {
  const { user } = useAuth();
  const can = (action) => user.is_superuser || user.permissions.includes(`catalog.${action}_brand`);
  const [brands, setBrands] = useState();
  const [loadError, setLoadError] = useState("");
  const [editing, setEditing] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api("/api/v1/catalog/brands/").then(setBrands).catch((e) => setLoadError(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  useLiveRefresh(load);
  if (loadError && !brands) return <ErrorState message={loadError} retry={load} />;
  if (!brands) return <Loading />;
  const run = async (place, work, done, failure) => {
    setBusy(true); setNotice(null);
    try { await work(); setNotice({ place, kind: "success", text: done }); setEditing(null); await load(); return true; }
    catch (e) { setNotice({ place, kind: "error", title: failure, text: e.message }); return false; }
    finally { setBusy(false); }
  };
  const save = (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = { name: new FormData(form).get("name"), active: editing ? new FormData(form).get("active") === "on" : true };
    return run("form", async () => {
      await api(`/api/v1/catalog/brands/${editing ? `${editing.id}/` : ""}`, { method: editing ? "PATCH" : "POST", body: JSON.stringify(data) });
      form.reset();
    }, `${data.name.trim()} ${editing ? "saved" : "added"}.`, editing ? "Could not save the brand." : "Could not add the brand.");
  };
  const remove = (brand) => run("list", () => api(`/api/v1/catalog/brands/${brand.id}/`, { method: "DELETE" }), `${brand.name} deleted.`, `Could not delete ${brand.name}.`);
  return <>
    <span className="eyebrow">Inventory</span>
    <h1>Brands</h1>
    <p className="muted">Brands label your products, such as Oraimo, Tecno or HP. Choose a product's brand when you add or edit it.</p>
    {(editing ? can("change") : can("add")) && <form key={editing?.id || "new"} className="formCard" onSubmit={(e) => void save(e)}>
      <h2>{editing ? `Edit ${editing.name}` : "Add a brand"}</h2>
      <label>Brand name<input name="name" required maxLength={120} defaultValue={editing?.name || ""} placeholder="e.g. Oraimo" /></label>
      {editing && <label className="checkRow"><input type="checkbox" name="active" defaultChecked={editing.active} /> Active (untick to hide it from new products)</label>}
      <button disabled={busy}>{busy ? "Saving…" : editing ? "Save brand" : "Add brand"}</button>
      {editing && <button type="button" className="secondary" onClick={() => setEditing(null)}>Cancel</button>}
      <Notice notice={notice} place="form" />
    </form>}
    {!brands.length ? <p className="muted">No brands yet.</p> : <div className="tableWrap"><table>
      <thead><tr><th>Brand</th><th>Products</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>{brands.map((brand) => <tr key={brand.id}>
        <td>{brand.name}</td><td>{brand.product_count}</td><td>{brand.active ? "Active" : "Inactive"}</td>
        <td>
          {can("change") && <button type="button" className="secondary" disabled={busy} onClick={() => { setNotice(null); setEditing(brand); }} aria-label={`Edit ${brand.name}`}>Edit</button>}
          {can("delete") && <button type="button" className="secondary" disabled={busy} onClick={() => void remove(brand)} aria-label={`Delete ${brand.name}`}>Delete</button>}
        </td>
      </tr>)}</tbody>
    </table></div>}
    <Notice notice={notice} place="list" />
  </>;
}
