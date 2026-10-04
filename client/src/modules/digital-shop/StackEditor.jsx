import { FormField } from "../../components/forms/FormField";
import { useEffect, useState } from "react";
import { removeStack, updateStack } from "./api";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";
import { FormError } from "../../components/forms/FormNotice";
export function StackEditor({ stack, zones, onClose, onChanged }) {
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [categories, setCategories] = useState([]);
  const [selectedCategories, setSelectedCategories] = useState(
    (stack.categories || []).map((category) => String(category.id)),
  );
  useEffect(() => {
    void api("/api/v1/catalog/categories/")
      .then(setCategories)
      .catch((reason) => setError({ place: "save", title: "Could not load product categories.", message: reason.message }));
  }, []);
  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    values.category_ids = selectedCategories;
    values.primary_category_id = selectedCategories[0] || "";
    try {
      await updateStack(stack.id, values);
      onChanged(Number(values.zone));
    } catch (reason) {
      setError({ place: "save", title: "Could not save the rack.", message: reason.message });
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
    setError(null);
    try {
      await removeStack(stack.id);
      onChanged();
    } catch (reason) {
      setError({ place: "remove", title: "Could not remove the rack.", message: reason.message });
      setSaving(false);
    }
  };
  return (
    <div className="shelfOverlay" role="presentation" onMouseDown={onClose}>
      <div
        className="shelfPanel"
        role="dialog"
        aria-modal="true"
        aria-label={`Edit rack ${stack.display_name}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="shelfPanelHeader">
          <div>
            <span className="eyebrow">Edit rack · {stack.code}</span>
            <h2>{stack.display_name}</h2>
          </div>
          <button
            type="button"
            className="shelfClose"
            onClick={onClose}
            aria-label="Close rack editor"
          >
            ×
          </button>
        </div>
        <p className="muted">
          The permanent rack and shelf codes stay unchanged when this rack
          moves.
        </p>
        <form className="formCard" onSubmit={save}>
          <FormField
            label="Rack name"
            name="display_name"
            defaultValue={stack.display_name}
            required
          />
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
            <select
              value={selectedCategories[0] || ""}
              onChange={(event) =>
                setSelectedCategories(
                  event.target.value
                    ? [event.target.value, ...selectedCategories.slice(1)]
                    : [],
                )
              }
            >
              <option value="">Leave unassigned</option>
              {categories
                .filter((category) => category.active)
                .map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Additional allowed categories
            <select
              multiple
              value={selectedCategories.slice(1)}
              onChange={(event) =>
                setSelectedCategories([
                  selectedCategories[0],
                  ...Array.from(
                    event.target.selectedOptions,
                    (option) => option.value,
                  ),
                ])
              }
            >
              {categories
                .filter(
                  (category) =>
                    category.active &&
                    String(category.id) !== selectedCategories[0],
                )
                .map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
            </select>
          </label>
          <div className="formGrid">
            <FormField
              label="X position (ft)"
              name="x"
              type="number"
              min="0"
              step="0.01"
              defaultValue={stack.x}
              required
            />
            <FormField
              label="Y position (ft)"
              name="y"
              type="number"
              min="0"
              step="0.01"
              defaultValue={stack.y}
              required
            />
            <FormField
              label="Width (ft)"
              name="width"
              type="number"
              min="0.01"
              step="0.01"
              defaultValue={stack.width}
              required
            />
            <FormField
              label="Height (ft)"
              name="height"
              type="number"
              min="0.01"
              step="0.01"
              defaultValue={stack.height}
              required
            />
            <FormField
              label="Depth (ft)"
              name="depth"
              type="number"
              min="0.01"
              step="0.01"
              defaultValue={stack.depth}
              required
            />
            <FormField
              label="Orientation °"
              name="rotation"
              type="number"
              step="0.01"
              defaultValue={stack.rotation}
              required
            />
          </div>
          <label>
            Notes
            <textarea name="notes" defaultValue={stack.notes} />
          </label>
          <button disabled={saving}>
            {saving ? "Saving…" : "Save rack position"}
          </button>
          {error?.place === "save" && <FormError title={error.title} message={error.message} />}
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
          {error?.place === "remove" && <FormError title={error.title} message={error.message} />}
        </section>
      </div>
    </div>
  );
}
