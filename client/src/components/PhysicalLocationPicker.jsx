import { useEffect, useMemo, useState } from "react";

export function PhysicalLocationPicker({ zones = [], value, onChange, required = false }) {
  const activeZones = zones.filter((zone) => zone.active);
  const selected = useMemo(() => activeZones.flatMap((zone) => (zone.stacks || []).flatMap((stack) => (stack.levels || []).flatMap((level) => (level.shelves || []).map((shelf) => ({ shelf, zone, stack, level }))))).find(({ shelf }) => shelf.id === value), [activeZones, value]);
  const [zoneId, setZoneId] = useState(selected?.zone.id ?? activeZones[0]?.id);
  const zone = activeZones.find((item) => item.id === zoneId);
  const stacks = (zone?.stacks || []).filter((stack) => stack.active);
  const [stackId, setStackId] = useState(selected?.stack.id ?? stacks[0]?.id);
  const stack = stacks.find((item) => item.id === stackId);
  const levels = (stack?.levels || []).filter((level) => level.active).sort((a, b) => a.level_number - b.level_number);
  const [levelId, setLevelId] = useState(selected?.level.id ?? levels[0]?.id);
  const level = levels.find((item) => item.id === levelId);
  const shelves = (level?.shelves || []).filter((shelf) => shelf.active);
  useEffect(() => { if (selected) { setZoneId(selected.zone.id); setStackId(selected.stack.id); setLevelId(selected.level.id); } }, [selected]);
  useEffect(() => { if (!zone?.stacks?.some((item) => item.id === stackId && item.active)) { const next = stacks[0]; setStackId(next?.id); setLevelId(next?.levels?.find((item) => item.active)?.id); onChange?.(""); } }, [zoneId]);
  useEffect(() => { if (!stack?.levels?.some((item) => item.id === levelId && item.active)) { setLevelId(levels[0]?.id); onChange?.(""); } }, [stackId]);
  useEffect(() => { if (value && !shelves.some((shelf) => shelf.id === value)) onChange?.(""); }, [levelId]);
  const path = selected ? `${selected.shelf.code} — ${selected.zone.name} / ${selected.stack.display_name} / Level ${selected.level.level_number} / ${selected.shelf.display_name}` : "No compartment selected";
  return <fieldset className="locationPicker"><legend>Exact placement</legend>{!activeZones.length ? <p className="muted">No active shop areas are configured.</p> : <><label>Shop area<select value={zoneId || ""} onChange={(event) => { const next = activeZones.find((item) => item.id === Number(event.target.value)); setZoneId(next?.id); setStackId(undefined); setLevelId(undefined); onChange?.(""); }} required={required}><option value="">Choose area</option>{activeZones.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Rack<select value={stackId || ""} onChange={(event) => { const next = stacks.find((item) => item.id === Number(event.target.value)); setStackId(next?.id); setLevelId(undefined); onChange?.(""); }} required={required}><option value="">Choose rack</option>{stacks.map((item) => <option key={item.id} value={item.id}>{item.code} — {item.display_name}</option>)}</select></label><label>Level<select value={levelId || ""} onChange={(event) => { setLevelId(Number(event.target.value)); onChange?.(""); }} required={required}><option value="">Choose level</option>{levels.map((item) => <option key={item.id} value={item.id}>Level {item.level_number}</option>)}</select></label><label>Compartment<select value={value || ""} onChange={(event) => onChange?.(event.target.value ? Number(event.target.value) : "")} required={required}><option value="">Choose compartment</option>{shelves.map((item) => <option key={item.id} value={item.id}>{item.code} — {item.display_name}</option>)}</select></label><small className="muted locationPath">{path}</small></>}</fieldset>;
}
