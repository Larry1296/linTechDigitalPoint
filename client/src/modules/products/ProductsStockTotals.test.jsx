import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["catalog.view_product", "catalog.change_product", "catalog.delete_product"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));
vi.mock("../digital-shop/api", () => ({ loadZonesIfUsed: async () => [] }));
let STOCK = { units: "506", products: 80, value_at_selling_price: "95050.00", value_at_cost: "48369.60", cost_missing: 1 };
import { api } from "../../core/api/client";
import { ProductsPage } from "./ProductsPage";

const product = (id, name) => ({ id, name, product_type: "STOCK_ITEM", active: true, category: 1, brand_name: "",
  variants: [{ id, sku: `SKU-${id}`, selling_price: "300", available: "5", minimum_stock: "1", images: [] }] });
beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path) => (path.includes("?page=") ? { results: [product(1, "MORIMAXE"), product(2, "AMAZON HEAD")], next: null }
    : path.includes("categories/available") ? [{ id: 1, path: ["Chargers"] }] : path.includes("category-counts") ? { categories: { 1: 2 }, other: 0, stock: STOCK } : path.endsWith("delete-check/") ? [] : []));
});


it("shows the stock held now at BP and at SP, with the profit if it all sells", async () => {
  render(<MemoryRouter initialEntries={["/"]}><ProductsPage /></MemoryRouter>);
  const totals = await screen.findByRole("region", { name: "Stock you hold now" });
  expect(totals).toHaveTextContent("Items in stock506");
  expect(totals).toHaveTextContent("Stock total at buying price (BP)KSh 48,369.6");
  expect(totals).toHaveTextContent("1 delivery has no buying price yet");
  expect(totals).toHaveTextContent("Stock total at selling price (SP)KSh 95,050");
  expect(totals).toHaveTextContent("Profit if it all sellsKSh 46,680.4");
});

it("shows only the SP total to staff who may not see buying prices", async () => {
  STOCK = { units: "506", products: 80, value_at_selling_price: "95050.00" };
  render(<MemoryRouter initialEntries={["/"]}><ProductsPage /></MemoryRouter>);
  const totals = await screen.findByRole("region", { name: "Stock you hold now" });
  expect(totals).toHaveTextContent("Stock total at selling price (SP)");
  expect(totals).not.toHaveTextContent("buying price");
  expect(totals).not.toHaveTextContent("Profit");
});
