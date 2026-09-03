import { useMemo, useState } from "react";
import type { Zone } from "../types";

export function PhysicalLocationPicker({
  zones,
  value,
  onChange,
}: {
  zones: Zone[];
  value?: number;
  onChange: (shelfId: number) => void;
}) {
  const initial = useMemo(
    () =>
      zones
        .flatMap((z) =>
          z.stacks.flatMap((s) => s.levels.flatMap((l) => l.shelves)),
        )
        .find((s) => s.id === value),
    [zones, value],
  );
  const [zoneId, setZoneId] = useState<number | undefined>(
    initial?.zone || zones[0]?.id,
  );
  const zone = zones.find((z) => z.id === zoneId);
  const [stackId, setStackId] = useState<number | undefined>(
    initial?.stack_id || zone?.stacks[0]?.id,
  );
  const stack = zone?.stacks.find((s) => s.id === stackId);
  const [levelId, setLevelId] = useState<number | undefined>(
    initial?.level || stack?.levels[0]?.id,
  );
  const level = stack?.levels.find((l) => l.id === levelId);
  return (
    <fieldset className="locationPicker">
      <legend>Physical location</legend>
      <label>
        Zone
        <select
          value={zoneId || ""}
          onChange={(e) => {
            const next = zones.find((z) => z.id === +e.target.value);
            setZoneId(next?.id);
            setStackId(next?.stacks[0]?.id);
            setLevelId(next?.stacks[0]?.levels[0]?.id);
          }}
        >
          {zones
            .filter((z) => z.active)
            .map((z) => (
              <option value={z.id} key={z.id}>
                {z.name}
              </option>
            ))}
        </select>
      </label>
      <label>
        Shelf Stack
        <select
          value={stackId || ""}
          onChange={(e) => {
            const next = zone?.stacks.find((s) => s.id === +e.target.value);
            setStackId(next?.id);
            setLevelId(next?.levels[0]?.id);
          }}
        >
          {zone?.stacks
            .filter((s) => s.active)
            .map((s) => (
              <option value={s.id} key={s.id}>
                {s.code} — {s.display_name}
              </option>
            ))}
        </select>
      </label>
      <label>
        Level
        <select
          value={levelId || ""}
          onChange={(e) => setLevelId(+e.target.value)}
        >
          {stack?.levels
            .filter((l) => l.active)
            .map((l) => (
              <option value={l.id} key={l.id}>
                Level {l.level_number}
              </option>
            ))}
        </select>
      </label>
      <label>
        Exact shelf
        <select value={value || ""} onChange={(e) => onChange(+e.target.value)}>
          <option value="">Choose shelf</option>
          {level?.shelves
            .filter((s) => s.active)
            .map((s) => (
              <option value={s.id} key={s.id}>
                {s.code} — {s.display_name}
              </option>
            ))}
        </select>
      </label>
    </fieldset>
  );
}
