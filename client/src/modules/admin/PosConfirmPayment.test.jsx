import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PosPage } from "./AdminPages";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
const permissions = vi.hoisted(() => ({ list: [] }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: permissions.list } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));

const earphones = { id: 7, product_name: "Oraimo earphones", variant_name: "Original", sku: "ORA-1", selling_price: "300.00",
  minimum_price: "250.00", available: "3", product_type: "STOCK_ITEM", category_name: "Audio" };
beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path) => {
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return [earphones];
    if (path === "/api/v1/commerce/pos/complete/") return { sale_id: 9, receipt_number: "POS-9", total: "250.00",
      waiting_payment: { id: 41, method: "MPESA", amount: "250.00", reference: "SJK4H7XQ2P" } };
    if (path === "/api/v1/commerce/payments/41/confirm/") return { id: 41, status: "COMPLETED" };
    return [];
  });
});

async function sellByMpesa() {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /Oraimo earphones/ }));
  const cart = screen.getByRole("heading", { name: "Current sale" }).closest("form");
  fireEvent.change(within(cart).getByLabelText(/Agreed price for/), { target: { value: "250" } });
  fireEvent.change(within(cart).getByLabelText("Payment"), { target: { value: "MPESA" } });
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: "Complete sale" })); });
}

it("confirms an M-Pesa payment right after the sale, using the code typed at the till", async () => {
  permissions.list = ["commerce.add_sale", "commerce.change_payment"];
  await sellByMpesa();
  const box = screen.getByRole("group", { name: "Confirm M-Pesa payment" });
  expect(box).toHaveTextContent("250 is waiting for confirmation");
  expect(within(box).getByLabelText(/M-Pesa code/)).toHaveValue("SJK4H7XQ2P");
  await act(async () => { fireEvent.click(within(box).getByRole("button", { name: "Confirm money received" })); });
  const call = api.mock.calls.find(([p]) => p === "/api/v1/commerce/payments/41/confirm/");
  expect(JSON.parse(call[1].body)).toEqual({ reference: "SJK4H7XQ2P" });
  expect(screen.queryByRole("group", { name: "Confirm M-Pesa payment" })).toBeNull();
  expect(screen.getByText("Payment confirmed (SJK4H7XQ2P).")).toBeInTheDocument();
});

it("tells a cashier who cannot confirm payments who can", async () => {
  permissions.list = ["commerce.add_sale"];
  await sellByMpesa();
  const box = screen.getByRole("group", { name: "Confirm M-Pesa payment" });
  expect(within(box).queryByRole("button", { name: "Confirm money received" })).toBeNull();
  expect(box).toHaveTextContent("confirm it under Sales");
});
