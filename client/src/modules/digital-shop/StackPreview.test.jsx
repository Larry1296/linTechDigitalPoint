import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { StackPreview } from "./StackPreview";

const shelf = (id, level) => ({ id, code: `R1-L0${level}-S01`, display_name: `Level ${level} Compartment 1`, physical_label: "", position_in_level: 1, total_quantity: "0" });

it("draws a saved rack from the floor up: Level 1 at the bottom, just above the floor", () => {
  const stack = { id: 1, code: "R1", display_name: "Chargers", levels: [1, 3, 2].map((n) => ({ level_number: n, shelves: [shelf(n, n)] })) };
  const { container } = render(<StackPreview stack={stack} name="Chargers" width={4} height={6} depth={1} />);
  expect([...container.querySelectorAll(".rackLevelLabel")].map((label) => label.textContent)).toEqual(["Level 3", "Level 2", "Level 1"]);
  expect(container.querySelector(".rackFrame + .rackFloor")).toHaveTextContent("Floor");
  expect(screen.getByRole("button", { name: "Level 1, Shelf 1, 0 units" })).toBeInTheDocument();
});
