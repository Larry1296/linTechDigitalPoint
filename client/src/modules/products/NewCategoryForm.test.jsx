import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../core/api/client";
import { ProductForm } from "./ProductForm";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
let permissions;
vi.mock("../../core/auth/AuthContext", () => ({
  useAuth: () => ({ user: { permissions, organization: { enabled_modules: ["inventory", "locations"] } } }),
}));

const zones = [{ id: 1, active: true, name: "Left wall", stacks: [
  { id: 7, active: true, code: "LW-R01", display_name: "PHONE ACCESSORIES", levels: [] },
  { id: 8, active: false, code: "LW-R02", display_name: "Old rack", levels: [] },
] }];
const PHONE = { id: 30, name: "PHONE ACCESSORIES", path: ["PHONE ACCESSORIES"], rack_ids: [7], rack_names: ["PHONE ACCESSORIES"], available: true };
let categories;

beforeEach(() => {
  vi.clearAllMocks();
  permissions = ["catalog.add_category", "inventory.change_shelfstack"];
  categories = [PHONE];
  api.mockImplementation(async (path, options) => {
    if (path === "/api/v1/catalog/categories/" && options?.method === "POST") {
      const body = JSON.parse(options.body);
      const created = { id: 50, name: body.name, parent: body.parent };
      categories = [...categories, { id: 50, name: `${body.name} – PHONE ACCESSORIES`, path: ["PHONE ACCESSORIES", body.name], rack_ids: [7], rack_names: ["PHONE ACCESSORIES"], available: true }];
      return created;
    }
    if (path.includes("categories/available")) return categories;
    return [];
  });
});

const open = async () => {
  render(<ProductForm zones={zones} onSaved={vi.fn()} />);
  await screen.findByRole("option", { name: "PHONE ACCESSORIES" });
  fireEvent.click(screen.getByRole("button", { name: "New category" }));
};

it("creates a missing category under a parent, and it is chosen for the product", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("New category name"), { target: { value: "Memory cards" } });
  fireEvent.change(screen.getByLabelText("Inside"), { target: { value: "30" } });
  // A sub-category uses its parent's rack unless another is chosen.
  expect(within(screen.getByLabelText("Rack (physical shelf)")).getByRole("option", { name: "Same as its parent: PHONE ACCESSORIES" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add category" }));
  await waitFor(() => expect(screen.getByLabelText(/Product category/)).toHaveValue("50"));
  const [, request] = api.mock.calls.find(([path, options]) => path === "/api/v1/catalog/categories/" && options?.method === "POST");
  expect(JSON.parse(request.body)).toEqual({ name: "Memory cards", parent: 30, active: true });
  expect(screen.queryByLabelText("New category name")).not.toBeInTheDocument();
});

it("a new top-level category needs a rack, chosen from the active racks", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("New category name"), { target: { value: "Computer accessories" } });
  const rack = screen.getByLabelText("Rack (physical shelf)");
  expect(within(rack).queryByRole("option", { name: /Old rack/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add category" })).toBeDisabled();
  fireEvent.change(rack, { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: "Add category" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/catalog/categories/", expect.objectContaining({ method: "POST" })));
  const [, request] = api.mock.calls.find(([path, options]) => path === "/api/v1/catalog/categories/" && options?.method === "POST");
  expect(JSON.parse(request.body)).toEqual({ name: "Computer accessories", parent: null, active: true, rack_id: 7 });
});

it("hides the rack choice without Shelf management, and New category without permission to add one", async () => {
  permissions = ["catalog.add_category"];
  await open();
  expect(screen.queryByLabelText("Rack (physical shelf)")).not.toBeInTheDocument();
  expect(screen.getByText(/Only someone with Shelf management/)).toBeInTheDocument();
  permissions = [];
  render(<ProductForm zones={zones} onSaved={vi.fn()} />);
  await waitFor(() => expect(screen.queryAllByRole("button", { name: "New category" })).toHaveLength(0));
});
