import { useEffect, useState } from "react";
import { removeStack, updateStack } from "./api";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";
export function StackEditor({ stack, zones, onClose, onChanged }) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [categories, setCategories] = useState([]);
  const [selectedCategories, setSelectedCategories] = useState((stack.categories || []).map((category) => String(category.id)));
  useEffect(() => { void api("/api/v1/catalog/categories/").then(setCategories).catch((reason) => setError(reason.message)); }, []);
  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    values.category_ids = selectedCategories;
    values.primary_category_id = selectedCategories[0] || "";
    try {
      await updateStack(stack.id, values);
      onChanged(Number(values.zone));
    } catch (reason) {
      setError(reason.message);
      setSaving(false);
    }
  };
  const remove = async () => {
    if (
      !(await confirmAction({
        title: `Remove ${stack.display_name}?`,
        text: "Only an empty rack can be removed. This cannot be undone.",
        confirmButtonText: "Remove rack",
      }))
    )
      return;
    setSaving(true);
    setError("");
    try {
      await removeStack(stack.id);
      onChanged();
    } catch (reason) {
      setError(reason.message);
      setSaving(false);
    }
  };
  return (
    <div className="shelfOverlay" role="presentation" onMouseDown={onClose}>
      <aside
        className="shelfPanel"
        role="dialog"
        aria-modal="true"
        aria-label="Move or edit shelf rack"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="shelfPanelHeader">
          <div>
            <span className="eyebrow">Shelf rack</span>
            <strong>{stack.code}</strong>
          </div>
          <button
            className="shelfClose"
            onClick={onClose}
            aria-label="Close rack editor"
          >
            × <span>Close</span>
          </button>
        </div>
        <p className="muted">
          The permanent rack and shelf codes stay unchanged when this rack
          moves.
        </p>
        {error && <p className="formError">{error}</p>}
        <form className="formCard" onSubmit={save}>
          <label>
            Rack name
            <input
              name="display_name"
              defaultValue={stack.display_name}
              required
            />
          </label>
          <label>
            Shop area
            <select name="zone" defaultValue={stack.zone}>
              {zones
                .filter((zone) => zone.active)
                .map((zone) => (
                  <option key={zone.id} value={zone.id}>
                    {zone.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Primary merchandise category (optional)
            <select value={selectedCategories[0] || ""} onChange={(event) => setSelectedCategories(event.target.value ? [event.target.value, ...selectedCategories.slice(1)] : [])}>
              <option value="">Leave unassigned</option>
              {categories.filter((category) => category.active).map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </select>
          </label>
          <label>
            Additional allowed categories
            <select multiple value={selectedCategories.slice(1)} onChange={(event) => setSelectedCategories([selectedCategories[0], ...Array.from(event.target.selectedOptions, (option) => option.value)])}>
              {categories.filter((category) => category.active && String(category.id) !== selectedCategories[0]).map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </select>
          </label>
          <div className="formGrid">
            <label>
              X position (ft)
              <input
                name="x"
                type="number"
                min="0"
                step="0.01"
                defaultValue={stack.x}
                required
              />
            </label>
            <label>
              Y position (ft)
              <input
                name="y"
                type="number"
                min="0"
                step="0.01"
                defaultValue={stack.y}
                required
              />
            </label>
            <label>
              Width (ft)
              <input
                name="width"
                type="number"
                min="0.01"
                step="0.01"
                defaultValue={stack.width}
                required
              />
            </label>
            <label>
              Height (ft)
              <input
                name="height"
                type="number"
                min="0.01"
                step="0.01"
                defaultValue={stack.height}
                required
              />
            </label>
            <label>
              Depth (ft)
              <input
                name="depth"
                type="number"
                min="0.01"
                step="0.01"
                defaultValue={stack.depth}
                required
              />
            </label>
            <label>
              Orientation °
              <input
                name="rotation"
                type="number"
                step="0.01"
                defaultValue={stack.rotation}
                required
              />
            </label>
          </div>
          <label>
            Notes
            <textarea name="notes" defaultValue={stack.notes} />
          </label>
          <button disabled={saving}>
            {saving ? "Saving…" : "Save rack position"}
          </button>
        </form>
        <section className="dangerZone">
          <h3>Remove rack</h3>
          <p>
            Empty racks are archived safely. If stock remains, removal is
            blocked until it is transferred.
          </p>
          <button
            className="danger"
            disabled={saving}
            onClick={() => void remove()}
          >
            Remove empty rack
          </button>
        </section>
      </aside>
    </div>
  );
}
