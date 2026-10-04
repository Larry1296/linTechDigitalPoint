import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { CategoriesPage } from "./CategoriesPage";
import { deleteCategory, loadCategories, saveCategory } from "./api";

vi.mock("./api", () => ({ loadCategories: vi.fn(), saveCategory: vi.fn(), deleteCategory: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { is_superuser: false,
  permissions: ["catalog.view_category", "catalog.add_category", "catalog.change_category", "catalog.delete_category"] } }) }));

const rows = [
  { id: 1, name: "Mobile Accessories", parent: null, active: true, product_count: 4, racks: ["Phone Accessories Rack"] },
  { id: 2, name: "Computer Acessories", parent: null, active: true, product_count: 0, racks: [] },
];
beforeEach(() => { vi.clearAllMocks(); loadCategories.mockResolvedValue(rows); });

it("lists categories with their products and racks, and lets the owner fix, add and delete them", async () => {
  render(<MemoryRouter><CategoriesPage /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Product categories" })).toBeInTheDocument();
  const mobile = screen.getByRole("row", { name: /Mobile Accessories/ });
  expect(within(mobile).getByText("4")).toBeInTheDocument();
  expect(within(mobile).getByText("Phone Accessories Rack")).toBeInTheDocument();
  expect(within(screen.getByRole("row", { name: /Computer Acessories/ })).getByText("Not on a rack")).toBeInTheDocument();

  saveCategory.mockResolvedValue({ ...rows[1], name: "Computer Accessories" });
  fireEvent.click(screen.getByRole("button", { name: "Edit Computer Acessories" }));
  fireEvent.change(screen.getByLabelText("Category name"), { target: { value: "Computer Accessories" } });
  fireEvent.click(screen.getByRole("button", { name: "Save category" }));
  await screen.findByText("Computer Accessories updated.");
  expect(saveCategory).toHaveBeenCalledWith(2, { name: "Computer Accessories", parent: null, active: true });
  expect(loadCategories).toHaveBeenCalledTimes(2);

  deleteCategory.mockResolvedValue(undefined);
  fireEvent.click(screen.getByRole("button", { name: "Delete Computer Acessories" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm delete Computer Acessories" }));
  await screen.findByText("Computer Acessories deleted.");
  expect(deleteCategory).toHaveBeenCalledWith(2);
});
