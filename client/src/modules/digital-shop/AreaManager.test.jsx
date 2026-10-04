import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AreaManager } from "./AreaManager";
import { createZone, removeZone, updateZone } from "./api";

vi.mock("./api", () => ({ createZone: vi.fn(), removeZone: vi.fn(), updateZone: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));

const zones = [
  { id: 1, name: "Left Wall", width: "20.00", height: "10.00", stacks: [{ id: 5 }] },
  { id: 2, name: "Electrical & Masonry Accessories", width: "12.00", height: "8.00", stacks: [] },
];
beforeEach(() => vi.clearAllMocks());

function renderAreas(selected = 2, onAddRack = vi.fn()) {
  const onChanged = vi.fn();
  render(<AreaManager zones={zones} selected={selected} onSelect={vi.fn()} onChanged={onChanged} canAdd canChange canAddRack onAddRack={onAddRack} />);
  return onChanged;
}

it("puts adding a rack on the selected area, separate from adding another area", () => {
  const onAddRack = vi.fn();
  renderAreas(1, onAddRack);
  fireEvent.click(screen.getByRole("button", { name: "Add rack to Left Wall" }));
  expect(onAddRack).toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Add another area" })).toBeInTheDocument();
});

it("edits the selected area's name and size", async () => {
  updateZone.mockResolvedValue({ id: 2 });
  const onChanged = renderAreas();
  expect(screen.getByText(/12 × 8 ft · 0 racks/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit area" }));
  fireEvent.change(screen.getByLabelText("Area name"), { target: { value: "Electrical corner" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save area" })); });
  expect(updateZone).toHaveBeenCalledWith(2, { name: "Electrical corner", width: "12.00", height: "8.00" });
  expect(screen.getByRole("status")).toHaveTextContent("Electrical corner saved.");
  expect(onChanged).toHaveBeenCalledWith(2);
});

it("explains a refused removal right under the area actions", async () => {
  removeZone.mockRejectedValue(new Error("Left Wall still has 1 rack: Phone Accessories Rack. Remove them or move them to another area first."));
  renderAreas(1);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Remove area" })); });
  expect(removeZone).toHaveBeenCalledWith(1);
  expect(screen.getByRole("alert")).toHaveTextContent("Could not remove Left Wall. Left Wall still has 1 rack");
});

it("adds a new area", async () => {
  createZone.mockResolvedValue({ id: 9 });
  const onChanged = renderAreas();
  fireEvent.click(screen.getByRole("button", { name: "Add another area" }));
  fireEvent.change(screen.getByLabelText("Area name"), { target: { value: "Store room" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add area" })); });
  expect(createZone).toHaveBeenCalledWith({ name: "Store room", width: "20", height: "10" });
  expect(onChanged).toHaveBeenCalledWith(9);
});

it("after adding an area, scrolls back up to it and points to adding its first rack", async () => {
  const { useState } = await import("react");
  const scroll = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = scroll;
  createZone.mockResolvedValue({ id: 3 });
  function Page() {
    const [rows, setRows] = useState(zones);
    const [selected, setSelected] = useState(1);
    return <AreaManager zones={rows} selected={selected} onSelect={setSelected} canAdd canChange canAddRack onAddRack={vi.fn()}
      onChanged={async (id) => { setRows([...zones, { id: 3, name: "Counter", width: "8", height: "4", stacks: [] }]); setSelected(id); }} />;
  }
  render(<Page />);
  fireEvent.click(screen.getByRole("button", { name: "Add another area" }));
  fireEvent.change(screen.getByLabelText("Area name"), { target: { value: "Counter" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add area" })); });
  const toolbar = screen.getByLabelText("Actions for Counter");
  expect(toolbar).toHaveClass("justAdded");
  expect(toolbar).toContainElement(screen.getByRole("status"));
  expect(screen.getByRole("status")).toHaveTextContent("Counter added. Next, click “Add rack to Counter” to place its racks.");
  expect(screen.getByRole("button", { name: "Add rack to Counter" })).toHaveFocus();
  expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
  fireEvent.click(screen.getByRole("tab", { name: "Left Wall" }));  // moving on clears the pointer
  expect(screen.getByLabelText("Actions for Left Wall")).not.toHaveClass("justAdded");
  expect(screen.queryByRole("status")).toBeNull();
});
