import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { categoryDefaults } from "./productDefaults";
import { ProductForm } from "./ProductForm";
import { api } from "../../core/api/client";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [], organization: { enabled_modules: [] } } }) }));

const earphones = { id: 12, name: "Earphones – Phone Accessories", path: ["Phone Accessories", "Earphones"], available: true };
const product = (brand, min, target, shelf) => ({
  product_type: "STOCK_ITEM", brand,
  variants: [{ minimum_stock: min, target_stock: target }],
  locations: [{ preferred_shelf: shelf ? { id: shelf } : null }],
});

it("takes the category, and what most products filed there share", () => {
  expect(categoryDefaults(earphones, [product(3, "2.000", "10.000", 7), product(3, "2.000", "12.000", 7), product(3, "5.000", "10.000", null)])).toEqual({
    category: "12", categoryName: "Earphones – Phone Accessories", product_type: "STOCK_ITEM", brand: "3", minimum_stock: "2", target_stock: "10", shelf: "7",
  });
  // A brand is only suggested when every product there is that brand; an empty category still gives the category.
  expect(categoryDefaults(earphones, [product(3, "0", "0"), product(4, "0", "0")]).brand).toBe("");
  expect(categoryDefaults(earphones, [])).toMatchObject({ category: "12", product_type: "STOCK_ITEM", brand: "", minimum_stock: "" });
  expect(categoryDefaults({ ...earphones, available: false }, []).category).toBe("");
  expect(categoryDefaults({ id: "other" }, [])).toEqual({});
});

it("opens Add Product already filled in for the category it was opened from", async () => {
  api.mockImplementation(async (path) => path.includes("categories") ? [earphones] : [{ id: 3, name: "Oraimo" }]);
  render(<ProductForm zones={[]} onSaved={() => {}} defaults={{ category: "12", categoryName: earphones.name, product_type: "STOCK_ITEM", brand: "3", minimum_stock: "2", target_stock: "10" }} />);
  await waitFor(() => expect(screen.getByLabelText(/Product category/)).toHaveValue("12"));
  await waitFor(() => expect(screen.getByLabelText("Brand")).toHaveValue("3"));
  expect(screen.getByText(/Filled in for Earphones – Phone Accessories/)).toBeInTheDocument();
  expect(screen.getByLabelText("Minimum stock")).toHaveValue(2);
  expect(screen.getByLabelText("Target stock")).toHaveValue(10);
  expect(screen.getByLabelText("Product name")).toHaveValue("");
});
