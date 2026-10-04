import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["catalog.view_product", "catalog.change_product", "catalog.delete_product"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));
vi.mock("../digital-shop/api", () => ({ loadZonesIfUsed: async () => [] }));
import { api } from "../../core/api/client";
import { ProductsPage } from "./ProductsPage";

const product = (id, name) => ({ id, name, product_type: "STOCK_ITEM", active: true, category: 1, brand_name: "",
  variants: [{ id, sku: `SKU-${id}`, selling_price: "300", available: "5", minimum_stock: "1", images: [] }] });
beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path) => (path.includes("?page=") ? { results: [product(1, "MORIMAXE"), product(2, "AMAZON HEAD")], next: null }
    : path.includes("categories/available") ? [{ id: 1, path: ["Chargers"] }] : path.includes("category-counts") ? { categories: { 1: 2 }, other: 0 } : path.endsWith("delete-check/") ? [] : []));
});

it("shows no tick boxes or delete buttons until the owner chooses to delete one product or several", async () => {
  render(<MemoryRouter initialEntries={["/?category=1"]}><ProductsPage /></MemoryRouter>);
  await screen.findByText("MORIMAXE");
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Delete MORIMAXE/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete products" }));
  fireEvent.click(screen.getByRole("button", { name: "One product" }));
  expect(screen.getByRole("button", { name: "Delete MORIMAXE" })).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("button", { name: "Delete MORIMAXE" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete products" }));
  fireEvent.click(screen.getByRole("button", { name: "Several products" }));
  const bar = screen.getByRole("region", { name: "Delete products" });
  expect(within(bar).getByRole("button", { name: "Delete selected" })).toBeDisabled();
  fireEvent.click(screen.getByLabelText("Select MORIMAXE"));
  fireEvent.click(screen.getByLabelText("Select AMAZON HEAD"));
  expect(bar).toHaveTextContent("2 selected");
  fireEvent.click(within(bar).getByRole("button", { name: "Delete selected" }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
});
