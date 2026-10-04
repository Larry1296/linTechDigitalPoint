import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../core/api/client";
import { ProductLookupPage } from "./ProductLookupPage";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it("starts with lookup instead of loading the editable catalog", () => {
  render(<MemoryRouter><ProductLookupPage /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "Product Lookup" })).toBeInTheDocument();
  expect(screen.getByRole("combobox")).toBeInTheDocument();
  expect(screen.queryByText("Add Product")).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});
it("shows selected availability and shelf details with a separate management link", async () => {
  api.mockResolvedValue({ id: 2, name: "Cable", category_name: "Accessories", product_type: "STOCK_ITEM", variants: [{ id: 3, name: "USB-C", sku: "CABLE-C", selling_price: "100", physical: "10", reserved: "4", available: "6" }], locations: [{ variant_id: 3, actual: [{ shelf_id: 7, shelf__code: "S1", shelf__zone__name: "Shop", shelf__display_name: "Front shelf", available: "6", reserved: "4" }] }] });
  render(<MemoryRouter initialEntries={["/admin/product-lookup?product=2&variant=3"]}><ProductLookupPage /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Cable — USB-C" })).toBeInTheDocument();
  expect(screen.getByText("6 available · 4 reserved")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open in catalog management →" })).toHaveAttribute("href", "/admin/products");
  expect(screen.queryByText("Latest buying price")).not.toBeInTheDocument();
  expect(screen.queryByText("Edit product details")).not.toBeInTheDocument();
});
