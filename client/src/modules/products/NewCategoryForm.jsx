import { useState } from "react";
import { api } from "../../core/api/client";
import { FormError } from "../../components/forms/FormNotice";
import { TextBox } from "../../components/forms/TextBox";

// Every active rack, as "Area — Rack", from the shop areas the product form already has.
export function activeRacks(zones = []) {
  return zones.filter((zone) => zone.active).flatMap((zone) => (zone.stacks || []).filter((stack) => stack.active)
    .map((stack) => ({ id: stack.id, label: `${zone.name} — ${stack.display_name}` })));
}

// Adds a category without leaving the product form: its name, where it sits (top level or under another
// category) and the rack that holds it, so products can be stocked in it straight away. A sub-category uses
// its parent's rack unless another one is chosen.
export function NewCategoryForm({ categories, zones, usesShelves, canAssignRack, onCreated, onCancel }) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const [rackId, setRackId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const racks = activeRacks(zones);
  const parent = categories.find((c) => String(c.id) === parentId);
  const inherited = parent?.rack_names?.length ? parent.rack_names.join(", ") : "";
  const needsRack = usesShelves && !inherited;
  const add = async () => {
    setBusy(true);
    setError("");
    try {
      const created = await api("/api/v1/catalog/categories/", { method: "POST", body: JSON.stringify({
        name: name.trim(), parent: parentId ? Number(parentId) : null, active: true, ...(rackId ? { rack_id: Number(rackId) } : {}),
      }) });
      await onCreated(created);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="inlineForm newCategory">
      <label>New category name<TextBox value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="e.g. Memory cards" autoFocus /></label>
      <label>Inside
        <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
          <option value="">Nothing: a top-level category</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{(c.path || [c.name]).join(" > ")}</option>)}
        </select>
      </label>
      {usesShelves && (canAssignRack ? (
        <label>Rack (physical shelf)
          <select value={rackId} onChange={(e) => setRackId(e.target.value)} required={needsRack}>
            <option value="">{inherited ? `Same as its parent: ${inherited}` : "Choose the rack that holds it"}</option>
            {racks.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </label>
      ) : needsRack && <small className="muted">Only someone with Shelf management can put a category on a rack. Until then, products can't be stocked in it.</small>)}
      {usesShelves && !racks.length && canAssignRack && <small className="muted">No racks yet. Add one in Shelf management first.</small>}
      <button type="button" disabled={busy || !name.trim() || (needsRack && canAssignRack && !rackId)} onClick={() => void add()}>Add category</button>
      <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      <FormError title="Could not add the category." message={error} />
    </div>
  );
}
