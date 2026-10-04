import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DigitalShopPage } from "./DigitalShopPage";
import { CategoryManager } from "./CategoryManager";
import { deleteCategory, loadCategories, loadZones, saveCategory } from "./api";
vi.mock("./api", () => ({ loadCategories: vi.fn(), loadZones: vi.fn(), saveCategory: vi.fn(), deleteCategory: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { is_superuser: true, permissions: [] } }) }));
vi.mock("./StackBuilder", () => ({ StackBuilder: () => null }));
vi.mock("./StackEditor", () => ({ StackEditor: () => null }));
vi.mock("./ShelfDetails", () => ({ ShelfDetails: () => null }));
beforeEach(() => { vi.clearAllMocks(); loadCategories.mockResolvedValue([]); loadZones.mockResolvedValue([]); });
it("Shelf Management sends category setup to the Categories page and offers racks only when categories exist", async () => {
  const { MemoryRouter } = await import("react-router-dom");
  loadZones.mockResolvedValue([{ id: 4, name: "Left Wall", width: "20", height: "10", stacks: [], unassigned_shelves: [] }]);
  const { unmount } = render(<MemoryRouter><DigitalShopPage /></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "Categories" })).toHaveAttribute("href", "/admin/categories");
  expect(screen.queryByLabelText("Category name")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Add rack/ })).not.toBeInTheDocument();
  expect(saveCategory).not.toHaveBeenCalled();
  unmount();
  loadCategories.mockResolvedValue([{ id: 1, name: "Mobile Accessories", parent: null, active: true }]);
  render(<MemoryRouter><DigitalShopPage /></MemoryRouter>);
  expect(await screen.findByRole("button", { name: "Add rack to Left Wall" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add another area" })).toBeInTheDocument();
  expect(screen.getByText("No racks in Left Wall yet. Use “Add rack to Left Wall” above.")).toBeInTheDocument();
});
it("shows server errors without discarding the owner's input", async () => {
  saveCategory.mockRejectedValue(new Error("A category with this name already exists."));
  render(<CategoryManager categories={[]} onSaved={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Category name"), { target: { value: "Mobile Accessories" } });
  fireEvent.click(screen.getByRole("button", { name: "Create category" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  expect(screen.getByLabelText("Category name")).toHaveValue("Mobile Accessories");
});
it("edits and deactivates categories without deleting their references", async () => {
  const root = { id: 1, name: "Mobile Accessories", parent: null, active: true };
  const child = { id: 2, name: "Cables", parent: 1, active: true };
  const onSaved = vi.fn();
  saveCategory.mockResolvedValue({ ...child, active: false });
  render(<CategoryManager categories={[root, child]} onSaved={onSaved} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit Cables" }));
  fireEvent.click(screen.getByLabelText("Active category"));
  fireEvent.click(screen.getByRole("button", { name: "Save category" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(saveCategory).toHaveBeenCalledWith(2, { name: "Cables", parent: 1, active: false });
});
it("deletes a leaf category outright after a confirm step, and blocks a parent with subcategories", async () => {
  const root = { id: 1, name: "Mobile Accessories", parent: null, active: true };
  const child = { id: 2, name: "Cables", parent: 1, active: true };
  const onDeleted = vi.fn();
  deleteCategory.mockResolvedValue(undefined);
  render(<CategoryManager categories={[root, child]} onSaved={vi.fn()} onDeleted={onDeleted} />);
  expect(screen.getByRole("button", { name: "Delete Mobile Accessories" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Delete Cables" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm delete Cables" }));
  await waitFor(() => expect(deleteCategory).toHaveBeenCalledWith(2));
  await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(2));
  expect(await screen.findByText("Cables deleted.")).toBeInTheDocument();
});
it("surfaces a blocked delete (e.g. products still assigned) without crashing", async () => {
  const category = { id: 3, name: "Wall Charger", parent: null, active: true };
  deleteCategory.mockRejectedValue(new Error("The operation conflicts with an existing record or business relationship."));
  render(<CategoryManager categories={[category]} onSaved={vi.fn()} onDeleted={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete Wall Charger" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm delete Wall Charger" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("conflicts with an existing record");
  expect(screen.getByRole("cell", { name: "Wall Charger" })).toBeInTheDocument();
});
const tree = [
  { id: 1, name: "ELECTRICAL & MASONRY ACCESSORIES", parent: null, active: true, product_count: 0, racks: ["Back Wall Rack"] },
  { id: 2, name: "TAPES", parent: 1, active: true, product_count: 2, racks: [] },
  { id: 3, name: "BULBS", parent: 1, active: true, product_count: 0, racks: [] },
  { id: 4, name: "AC", parent: 3, active: true, product_count: 1, racks: [] },
  { id: 5, name: "Accessories", parent: null, active: true, product_count: 0, racks: [] },
];
it("lists categories as a tree: parents first, sub-categories indented A–Z, racks inherited from the parent", () => {
  render(<CategoryManager categories={tree} onSaved={vi.fn()} />);
  const names = screen.getAllByRole("row").slice(1).map((row) => row.querySelector(".categoryName > span").textContent);
  expect(names).toEqual(["Accessories", "ELECTRICAL & MASONRY ACCESSORIES", "BULBS", "AC", "TAPES"]);
  const ac = screen.getByRole("row", { name: /^AC/ });
  expect(ac).toHaveAttribute("data-depth", "2");
  expect(ac).toHaveTextContent("ELECTRICAL & MASONRY ACCESSORIES › BULBS");
  expect(ac).toHaveTextContent("Back Wall Rack (through ELECTRICAL & MASONRY ACCESSORIES)");
  expect(screen.getByRole("row", { name: /^Accessories/ })).toHaveTextContent("Not on a rack");
  expect(screen.getByRole("row", { name: /^ELECTRICAL/ })).toHaveTextContent("3 with sub-categories");
  expect(within(screen.getByRole("group").closest("form")).getByRole("option", { name: "ELECTRICAL & MASONRY ACCESSORIES › BULBS › AC" })).toBeInTheDocument();
});
it("adds a sub-category with its parent already chosen", async () => {
  saveCategory.mockResolvedValue({ id: 6, name: "DC", parent: 3, active: true });
  render(<CategoryManager categories={tree} onSaved={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Add sub-category to BULBS" }));
  expect(screen.getByLabelText("Parent category")).toHaveValue("3");
  fireEvent.change(screen.getByLabelText("Category name"), { target: { value: "DC" } });
  fireEvent.click(screen.getByRole("button", { name: "Create category" }));
  await waitFor(() => expect(saveCategory).toHaveBeenCalledWith(null, { name: "DC", parent: 3, active: true }));
});
it("search keeps each match's parents visible", () => {
  const many = [...tree, ...[6, 7, 8, 9].map((id) => ({ id, name: `Other ${id}`, parent: null, active: true, racks: [] }))];
  render(<CategoryManager categories={many} onSaved={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Find a category"), { target: { value: "ac" } });
  const names = screen.getAllByRole("row").slice(1).map((row) => row.querySelector(".categoryName > span").textContent);
  expect(names).toEqual(["Accessories", "ELECTRICAL & MASONRY ACCESSORIES", "BULBS", "AC"]);
});
