import { useState } from "react";
import { createZone, removeZone, updateZone } from "./api";
import { confirmAction } from "../../core/ui/alerts";
import { FormField } from "../../components/forms/FormField";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";

// Areas are the walls or floor sections where racks stand; each keeps its real size.
export function AreaManager({ zones, selected, onSelect, onChanged, canAdd, canChange, canAddRack, onAddRack }) {
  const [mode, setMode] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const zone = zones.find((item) => item.id === selected);
  const open = (next) => { setMode(next); setNotice(null); };
  const run = async (work, failure, done) => {
    setBusy(true); setNotice(null);
    try {
      const result = await work();
      setMode(null);
      setNotice({ kind: "success", text: done });
      await onChanged(result?.id);
    } catch (e) {
      setNotice({ kind: "error", title: failure, text: e.message });
    } finally {
      setBusy(false);
    }
  };
  const values = (event) => {
    event.preventDefault();
    return Object.fromEntries(new FormData(event.currentTarget));
  };
  const save = (event) => {
    const data = values(event);
    return run(() => updateZone(zone.id, data), `Could not save ${zone.name}.`, `${data.name} saved.`);
  };
  const add = (event) => {
    const data = values(event);
    return run(() => createZone(data), "Could not add the area.", `${data.name} added. Use “Add rack to ${data.name}” to place its racks.`);
  };
  const remove = async () => {
    if (!(await confirmAction({
      title: `Remove ${zone.name}?`,
      text: "Only an area with no racks and no stock can be removed.",
      confirmButtonText: "Remove area",
    }))) return;
    await run(() => removeZone(zone.id), `Could not remove ${zone.name}.`, `${zone.name} removed.`);
  };
  const form = (title, onSubmit, submitLabel, current = {}) => <form key={title} className="formCard" onSubmit={(event) => void onSubmit(event)}>
    <h3>{title}</h3>
    <FormField label="Area name" name="name" defaultValue={current.name} required maxLength={120} placeholder="Left wall, Counter, Store room…" />
    <FormField label="Width (ft)" name="width" type="number" min="0.01" step="0.01" defaultValue={current.width ?? 20} required />
    <FormField label="Height (ft)" name="height" type="number" min="0.01" step="0.01" defaultValue={current.height ?? 10} required />
    <button disabled={busy}>{busy ? "Saving…" : submitLabel}</button>
    <button type="button" className="secondary" disabled={busy} onClick={() => open(null)}>Cancel</button>
    {notice?.kind === "error" && <FormError title={notice.title} message={notice.text} />}
  </form>;
  return <section className="areaManager" aria-labelledby="areas-heading">
    <h2 id="areas-heading">Shop areas</h2>
    <p className="muted">An area is a wall or part of the shop floor where racks stand.</p>
    {zones.length > 0 && <div className="tabs" role="tablist" aria-label="Shop areas">
      {zones.map((item) => <button key={item.id} type="button" role="tab" aria-selected={item.id === selected}
        className={item.id === selected ? "active" : ""} onClick={() => { onSelect(item.id); open(null); }}>{item.name}</button>)}
    </div>}
    {zone && <div className="areaToolbar" aria-label={`Actions for ${zone.name}`}>
      <p><strong>{zone.name}</strong> · {+zone.width} × {+zone.height} ft · {zone.stacks.length} rack{zone.stacks.length === 1 ? "" : "s"}</p>
      <div className="areaActions">
        {canAddRack && <button type="button" disabled={busy} onClick={onAddRack}>Add rack to {zone.name}</button>}
        {canChange && <button type="button" className="secondary" disabled={busy} onClick={() => open("edit")}>Edit area</button>}
        {canChange && <button type="button" className="secondary" disabled={busy} onClick={() => void remove()}>Remove area</button>}
      </div>
    </div>}
    {!zones.length && <p>Start by adding the first area of your shop, such as a wall or the counter.</p>}
    {canAdd && <div className="areaActions">
      <button type="button" className="secondary" disabled={busy} onClick={() => open("add")}>{zones.length ? "Add another area" : "Add area"}</button>
    </div>}
    {mode === "edit" && zone && form(`Edit ${zone.name}`, save, "Save area", zone)}
    {mode === "add" && form("Add an area", add, "Add area")}
    {!mode && notice && (notice.kind === "error"
      ? <FormError title={notice.title} message={notice.text} />
      : <FormSuccess message={notice.text} />)}
  </section>;
}
