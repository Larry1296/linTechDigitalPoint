import { useState } from "react";
import type { ShelfStack, Zone } from "../../types";
import { removeStack, updateStack } from "./api";

export function StackEditor({
  stack,
  zones,
  onClose,
  onChanged,
}: {
  stack: ShelfStack;
  zones: Zone[];
  onClose: () => void;
  onChanged: (zoneId?: number) => void;
}) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await updateStack(stack.id, values);
      onChanged(Number(values.zone));
    } catch (reason) {
      setError((reason as Error).message);
      setSaving(false);
    }
  };
  const remove = async () => {
    if (
      !window.confirm(
        `Remove ${stack.display_name}? Only an empty rack can be removed.`,
      )
    )
      return;
    setSaving(true);
    setError("");
    try {
      await removeStack(stack.id);
      onChanged();
    } catch (reason) {
      setError((reason as Error).message);
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
