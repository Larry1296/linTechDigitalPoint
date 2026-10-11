import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PosPage } from "./AdminPages";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
// A cashier: may sell, may not change prices or give discounts.
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["commerce.add_sale"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));

const charger = { id: 9, product_name: "Original Normal Full Charger", variant_name: "Standard", sku: "ORAIMO-ONFC-STANDARD",
  selling_price: "600.00", minimum_price: "500.00", available: "2", product_type: "STOCK_ITEM", category_name: "Mobile Accessories" };
beforeEach(() => vi.clearAllMocks());

it("lets a cashier agree a price below the lowest price, noting it for review", async () => {
  api.mockImplementation(async (path) => {
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return [charger];
    if (path === "/api/v1/commerce/pos/complete/") return { sale_id: 1, receipt_number: "POS-1", total: "550.00" };
    return [];
  });
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /Original Normal Full Charger/ }));
  const cart = screen.getByRole("heading", { name: "Current sale" }).closest("form");
  // The price is on the line straight away, with the range the customer can bargain within.
  expect(within(cart).queryByLabelText("Line discount")).not.toBeInTheDocument();
  expect(within(cart).getByText(/Bargain .*500 – 600/)).toBeInTheDocument();
  const price = within(cart).getByLabelText(/Agreed price for/);
  expect(price).toHaveValue(600);
  fireEvent.change(price, { target: { value: "550" } });
  expect(within(cart).queryByRole("status")).not.toBeInTheDocument();
  expect(within(cart).getByText(/50 off the asking price/)).toBeInTheDocument();
  fireEvent.change(price, { target: { value: "350" } });
  expect(price).toHaveAttribute("min", "0");
  expect(within(cart).getByRole("status")).toHaveTextContent("Below the usual lowest price (500)");
  expect(within(cart).queryByRole("alert")).not.toBeInTheDocument();
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: /^Complete sale/ })); });
  const sent = JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/commerce/pos/complete/")[1].body);
  expect(sent.items).toEqual([{ variant_id: 9, quantity: 1, unit_price: "350" }]);
});

it("lets the cashier clear the quantity box and type a new quantity", async () => {
  api.mockImplementation(async (path) => (path.startsWith("/api/v1/commerce/pos/catalog/") ? [{ ...charger, available: "10" }]
    : path === "/api/v1/commerce/pos/complete/" ? { sale_id: 1, receipt_number: "POS-1", total: "1800.00" } : []));
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /Original Normal Full Charger/ }));
  const quantity = screen.getByLabelText("Quantity of Original Normal Full Charger");
  fireEvent.change(quantity, { target: { value: "" } });
  expect(quantity).toHaveValue(null);          // stays empty while typing
  fireEvent.change(quantity, { target: { value: "3" } });
  expect(quantity).toHaveValue(3);
  const cart = screen.getByRole("heading", { name: "Current sale" }).closest("form");
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: /^Complete sale/ })); });
  const sent = JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/commerce/pos/complete/")[1].body);
  expect(sent.items[0].quantity).toBe(3);
});
