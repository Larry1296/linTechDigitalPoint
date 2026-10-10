import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductEditor } from "./ProductEditor";
import { api } from "../../core/api/client";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
let permissions = [];
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions } }) }));
beforeEach(() => { permissions = ["catalog.change_product", "catalog.change_productvariant"]; });
afterEach(() => vi.resetAllMocks());

const cable = {
  id: 5, name: "Cable", category: 1, brand: 3, product_type: "STOCK_ITEM", description: "", active: true, ecommerce_visible: true, online_orderable: true,
  images: [],
  variants: [
    { id: 2, name: "Red", sku: "RED", barcode: null, selling_price: "100", minimum_price: "0", minimum_stock: "1", target_stock: "10", active: true, physical: 8, available: 7, images: [] },
    { id: 3, name: "Blue", sku: "BLUE", barcode: "123", selling_price: "100", minimum_price: "0", minimum_stock: "1", target_stock: "10", active: true, images: [] },
  ],
};
const lookups = async (path) => {
  if (path === "/api/v1/catalog/categories/") return [{ id: 1, name: "Cables" }, { id: 2, name: "Chargers" }];
  if (path === "/api/v1/catalog/brands/") return [{ id: 3, name: "Oraimo" }];
  return {};
};
const patches = () => api.mock.calls.filter(([, o]) => o?.method === "PATCH").map(([url, o]) => [url, JSON.parse(o.body)]);

it("edits the product and every variant from one page with one save", async () => {
  api.mockImplementation(lookups);
  const saved = vi.fn();
  render(<ProductEditor product={cable} onSaved={saved} onClose={() => {}} />);
  await screen.findByRole("option", { name: "Chargers" });
  expect(screen.queryByLabelText(/physical/i)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Category"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Description"), { target: { value: "1m braided" } });
  fireEvent.click(screen.getByLabelText("Show in the online shop"));
  const red = within(screen.getByRole("group", { name: "Variant Red" }));
  fireEvent.change(red.getByLabelText("Selling price"), { target: { value: "150" } });
  fireEvent.change(red.getByLabelText(/Lowest price/), { target: { value: "120" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(patches()).toEqual([
    ["/api/v1/catalog/products/5/", { name: "Cable", category: "2", brand: 3, product_type: "STOCK_ITEM", description: "1m braided", active: true, ecommerce_visible: false, online_orderable: true }],
    // Blue was not touched, so it is not sent.
    ["/api/v1/catalog/variants/2/", { name: "Red", sku: "RED", barcode: null, selling_price: "150", minimum_price: "120", minimum_stock: "1", target_stock: "10", active: true }],
  ]);
});

it("names the price box when it holds something that is not a number instead of sending it", async () => {
  api.mockImplementation(lookups);
  render(<ProductEditor product={cable} onSaved={() => {}} onClose={() => {}} />);
  await screen.findByRole("option", { name: "Chargers" });
  const red = within(screen.getByRole("group", { name: "Variant Red" }));
  // A number box reports "" for "7o" (letter O typed for a zero).
  fireEvent.change(red.getByLabelText("Selling price"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(await screen.findByText(/Red: Selling price must be a number/)).toBeInTheDocument();
  expect(patches()).toEqual([]);
});

it("edits a service's pricing and cost without stock levels", async () => {
  api.mockImplementation(lookups);
  const saved = vi.fn();
  const service = { ...cable, product_type: "SERVICE", variants: [{ id: 4, name: "Standard", sku: "WIN", barcode: null, selling_price: "1000", minimum_price: "800", service_cost: "100", active: true, images: [] }] };
  render(<ProductEditor product={service} onSaved={saved} onClose={() => {}} />);
  expect(screen.queryByLabelText("Minimum stock")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Selling price"), { target: { value: "1200" } });
  fireEvent.change(screen.getByLabelText("Service cost"), { target: { value: "150" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(patches()[1]).toEqual(["/api/v1/catalog/variants/4/", { name: "Standard", sku: "WIN", barcode: null, selling_price: "1200", minimum_price: "800", service_cost: "150", active: true }]);
});

it("edits the buying price and quantity in the variant box and saves them with everything else", async () => {
  permissions = ["catalog.change_product", "catalog.change_productvariant", "accounting.view_profit", "inventory.adjust_stock"];
  const lot = { id: 9, reference: "OPENING", source: "opening", uncosted: false, buying_price: "150.00", can_correct: true };
  const context = (id) => id === "2"
    ? { locations: [{ shelf_id: 7, quantity: "3.000", reserved: "0.000" }, { shelf_id: 8, quantity: "2.000", reserved: "0.000" }], default_shelf_id: 7, latest_lot_id: 9 }
    : { locations: [], default_shelf_id: 1, latest_lot_id: null };
  api.mockImplementation(async (path) => {
    if (path === "/api/v1/inventory/variants/2/buying-prices/") return [lot];
    if (path.endsWith("/buying-prices/")) return [];
    const match = path.match(/adjustments\/variants\/(\d+)\//);
    if (match) return context(match[1]);
    return lookups(path);
  });
  const saved = vi.fn();
  render(<ProductEditor product={cable} onSaved={saved} onClose={() => {}} />);
  const red = within(screen.getByRole("group", { name: "Variant Red" }));
  const blue = within(screen.getByRole("group", { name: "Variant Blue" }));
  fireEvent.change(await red.findByLabelText("Buying price (BP)"), { target: { value: "1500" } });
  fireEvent.change(await red.findByLabelText("Quantity in stock"), { target: { value: "1" } });
  expect(blue.getByText(/No stock received yet/)).toBeInTheDocument();
  fireEvent.change(await blue.findByLabelText(/Buying price \(BP\)/), { target: { value: "80" } });
  fireEvent.change(blue.getByLabelText("Quantity in stock"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("Note (what happened)"), { target: { value: "Typed wrongly" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api).toHaveBeenCalledWith("/api/v1/inventory/lots/9/cost/", { method: "POST", body: JSON.stringify({ unit_cost: "1500", reason: "Typed wrongly" }) });
  const adjustments = api.mock.calls.filter(([url]) => url === "/api/v1/inventory/adjustments/").map(([, o]) => JSON.parse(o.body));
  // 5 → 1 takes 3 from the first shelf and 1 from the second; Blue's 4 new units are costed at the price typed.
  expect(adjustments.map((a) => [a.variant_id, a.shelf_id, a.expected_quantity, a.counted_quantity, a.lot_id, a.new_lot_unit_cost, a.reason])).toEqual([
    [2, 7, "3", "0", 9, undefined, "Data-entry correction"],
    [2, 8, "2", "1", 9, undefined, "Data-entry correction"],
    [3, 1, "0", "4", undefined, "80", "Data-entry correction"],
  ]);
});

it("keeps photos on the same page", async () => {
  api.mockImplementation(lookups);
  render(<ProductEditor product={cable} onSaved={() => {}} onClose={() => {}} />);
  expect(await screen.findByRole("region", { name: "Photos" })).toBeInTheDocument();
});

it("deletes a product entered by mistake and explains why a used product can only be hidden", async () => {
  let deletable = false;
  api.mockImplementation(async (path, options = {}) => {
    if (path.endsWith("/can-delete/")) return deletable ? { can_delete: true, reason: "" } : { can_delete: false, reason: "it has been sold" };
    if (options.method === "DELETE") return undefined;
    return [];
  });
  const saved = vi.fn();
  render(<ProductEditor product={{ id: 5, name: "Typo charger", active: true, variants: [], images: [] }} onSaved={saved} onClose={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete product" }));
  expect(await screen.findByText(/Typo charger can't be deleted because it has been sold. Untick Active/)).toBeInTheDocument();
  expect(api).not.toHaveBeenCalledWith("/api/v1/catalog/products/5/", { method: "DELETE" });
  deletable = true;
  fireEvent.click(screen.getByRole("button", { name: "Delete product" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api).toHaveBeenCalledWith("/api/v1/catalog/products/5/", { method: "DELETE" });
});
