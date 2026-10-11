import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { PhysicalLocationPicker } from "./PhysicalLocationPicker";
import { StackPreview } from "../modules/digital-shop/StackPreview";

it("shows physical labels in selectors and draws Level 1 at the bottom, just above the floor", () => {
  const levels = [1, 2, 3].map((n) => ({
    id: n, level_number: n, active: true,
    shelves: [1, 2].map((p) => ({ id: n * 10 + p, active: true,
      position_in_level: p, physical_label: `AL${n}C${p}S1`,
      code: `A-R01-L0${n}-S0${p}`, display_name: `Compartment ${p}`, total_quantity: 0 })),
  }));
  const stack = { id: 1, active: true, display_name: "Mobile Accessories Rack", levels };
  const zones = [{ id: 1, active: true, name: "Zone A", stacks: [stack] }];
  function PickerHarness() {
    const [value, setValue] = useState(11);
    return <PhysicalLocationPicker zones={zones} value={value} onChange={setValue} />;
  }
  render(<PickerHarness />);
  expect(screen.getByRole("option", { name: "AL1C1S1 — Compartment 1" })).toBeInTheDocument();
  for (const level of levels) {
    fireEvent.change(screen.getByLabelText("Level"), { target: { value: level.id } });
    for (const shelf of level.shelves) {
      expect(screen.getByRole("option", { name: `${shelf.physical_label} — ${shelf.display_name}` })).toBeInTheDocument();
    }
  }
  render(<StackPreview stack={stack} width={6} height={6} depth={1} />);
  const buttons = screen.getAllByRole("button");
  // Read top to bottom as the rack stands: the highest level first, Level 1 last (nearest the floor).
  expect(buttons.map((b) => b.querySelector("b").textContent)).toEqual([
    "AL3C1S1", "AL3C2S1", "AL2C1S1", "AL2C2S1", "AL1C1S1", "AL1C2S1",
  ]);
});
