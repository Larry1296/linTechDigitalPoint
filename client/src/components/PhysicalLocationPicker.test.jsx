import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PhysicalLocationPicker } from "./PhysicalLocationPicker";
import { StackPreview } from "../modules/digital-shop/StackPreview";

it("shows physical labels in selectors and renders levels top to bottom", () => {
  const levels = [1, 2, 3].map((n) => ({
    id: n, level_number: n, active: true,
    shelves: [1, 2].map((p) => ({ id: n * 10 + p, active: true,
      position_in_level: p, physical_label: `AL${n}C${p}S1`,
      code: `A-R01-L0${n}-S0${p}`, display_name: `Compartment ${p}`, total_quantity: 0 })),
  }));
  const stack = { id: 1, active: true, display_name: "Mobile Accessories Rack", levels };
  render(<PhysicalLocationPicker zones={[{ id: 1, active: true, name: "Zone A", stacks: [stack] }]} value={11} onChange={vi.fn()} />);
  expect(screen.getByRole("option", { name: "AL1C1S1 — Compartment 1" })).toBeInTheDocument();
  render(<StackPreview stack={stack} width={6} height={6} depth={1} />);
  const buttons = screen.getAllByRole("button");
  expect(buttons.map((b) => b.querySelector("b").textContent)).toEqual([
    "AL1C1S1", "AL1C2S1", "AL2C1S1", "AL2C2S1", "AL3C1S1", "AL3C2S1",
  ]);
});
