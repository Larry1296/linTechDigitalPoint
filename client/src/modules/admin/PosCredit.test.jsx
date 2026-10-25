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

it("adds a new customer at the till, takes part in cash and leaves the balance owed with a due date", async () => {
  let checkout;
  const paidSoFar = (payments) => payments.reduce((sum, p) => sum + Number(p.amount), 0);
  api.mockImplementation(async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : {};
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return [bulb];
    if (path === "/api/v1/commerce/customers/" && options.method === "POST") return { id: 31, name: "Jane Wanjiku", phone: "0712345678" };
    if (path === "/api/v1/commerce/customers/") return [];
    if (path === "/api/v1/commerce/pos/checkouts/" && options.method === "POST") {
      checkout = { id: 1, number: "POS-1", status: "AWAITING", total: "800.00", paid: "0", left: "800.00", open: "800.00", items: 1,
        customer_id: Number(body.customer_id), payments: [], till_payments: [] };
      return checkout;
    }
    if (path === "/api/v1/commerce/pos/checkouts/1/pay/") {
      const payments = [...checkout.payments, { id: checkout.payments.length + 1, method: body.method, status: "CONFIRMED",
        amount: body.method === "CASH" ? body.cash_given : checkout.left, change: body.method === "CASH" ? "0.00" : null }];
      const left = 800 - paidSoFar(payments);
      checkout = { ...checkout, payments, paid: String(paidSoFar(payments)), left: String(left), open: String(left),
        status: left ? "PART_PAID" : "COMPLETED", ...(left ? {} : { receipt: { sale_id: 1, receipt_number: "POS-1", total: "800.00" } }) };
      return checkout;
    }
    return [];
  });
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /50W Rechargeable Bulbs/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Complete sale/ }));
  const cart = screen.getByRole("heading", { name: "Current sale" }).closest("form");
  fireEvent.change(within(cart).getByLabelText(/Agreed price for/), { target: { value: "800" } });
  fireEvent.click(within(cart).getByText("Customer (optional)"));
  fireEvent.click(within(cart).getByRole("button", { name: "+ New customer" }));
  fireEvent.change(within(cart).getByLabelText("Customer name"), { target: { value: "Jane Wanjiku" } });
  fireEvent.change(within(cart).getByLabelText("Phone"), { target: { value: "0712345678" } });
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: "Save customer" })); });
  expect(within(cart).getByLabelText("Customer")).toHaveValue("31");
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: /^Charge/ })); });
  const sent = JSON.parse(api.mock.calls.find(([p, o]) => p === "/api/v1/commerce/pos/checkouts/" && o?.method === "POST")[1].body);
  expect(sent).toEqual(expect.objectContaining({ customer_id: "31", items: [{ variant_id: 4, quantity: 1, unit_price: "800" }] }));
  const panel = screen.getByRole("region", { name: /^Checkout POS-1/ });
  fireEvent.change(within(panel).getByLabelText("Cash received"), { target: { value: "500" } });
  await act(async () => { fireEvent.click(within(panel).getByRole("button", { name: /^Take .* cash$/ })); });
  fireEvent.click(within(panel).getByRole("tab", { name: /Owed/ }));
  fireEvent.change(within(panel).getByLabelText("Due date (optional)"), { target: { value: "2026-09-26" } });
  await act(async () => { fireEvent.click(within(panel).getByRole("button", { name: /^Leave .* owed by the customer$/ })); });
  const pays = api.mock.calls.filter(([p]) => p === "/api/v1/commerce/pos/checkouts/1/pay/").map(([, o]) => JSON.parse(o.body));
  expect(pays).toEqual([{ method: "CASH", cash_given: "500" }, { method: "OWED", due_date: "2026-09-26" }]);
  expect(await screen.findByRole("region", { name: "Sale complete" })).toBeInTheDocument();
});
