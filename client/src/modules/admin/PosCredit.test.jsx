import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PosPage } from "./AdminPages";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [
  "commerce.add_sale", "commerce.change_sale", "accounts.view_customerprofile", "accounts.add_customerprofile"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));

const bulb = { id: 4, product_name: "50W Rechargeable Bulbs", variant_name: "50W-Bulb", sku: "BULB", selling_price: "900.00",
  minimum_price: "800.00", available: "1", product_type: "STOCK_ITEM", category_name: "Electrical" };
beforeEach(() => vi.clearAllMocks());

it("adds a new customer at the till and records a part payment with the balance due later", async () => {
  api.mockImplementation(async (path, options = {}) => {
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return [bulb];
    if (path === "/api/v1/commerce/customers/" && options.method === "POST") return { id: 31, name: "Jane Wanjiku", phone: "0712345678" };
    if (path === "/api/v1/commerce/customers/") return [];
    if (path === "/api/v1/commerce/pos/complete/") return { sale_id: 1, receipt_number: "POS-1", total: "800.00" };
    return [];
  });
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /50W Rechargeable Bulbs/ }));
  const cart = screen.getByRole("heading", { name: "Current sale" }).closest("form");
  fireEvent.change(within(cart).getByLabelText(/Agreed price for/), { target: { value: "800" } });
  fireEvent.click(within(cart).getByText("Credit sale or partial payment"));
  fireEvent.click(within(cart).getByRole("button", { name: "+ New customer" }));
  fireEvent.change(within(cart).getByLabelText("Customer name"), { target: { value: "Jane Wanjiku" } });
  fireEvent.change(within(cart).getByLabelText("Phone"), { target: { value: "0712345678" } });
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: "Save customer" })); });
  expect(within(cart).getByLabelText(/^Customer \(needed/)).toHaveValue("31");
  fireEvent.change(within(cart).getByLabelText("Amount paid now"), { target: { value: "500" } });
  fireEvent.change(within(cart).getByLabelText("Balance due date"), { target: { value: "2026-09-26" } });
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: "Complete sale" })); });
  const sent = JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/commerce/pos/complete/")[1].body);
  expect(sent).toEqual(expect.objectContaining({ customer_id: "31", paid_amount: "500", due_date: "2026-09-26",
    items: [{ variant_id: 4, quantity: 1, unit_price: "800" }] }));
});
