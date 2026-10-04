import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["inventory.adjust_stock", "commerce.add_sale"] } }) }));
import { api } from "../../core/api/client";
import { StockCheckPage } from "./StockCheckPage";

const rows = [
  { id: 1, name: "Normal charger", variant: "Standard", sku: "CHG", on_shelf: "10.000", reserved: "0", selling_price: "300.00", lowest_price: "250.00", buying_price: "160.00" },
  { id: 2, name: "USB cable", variant: "Standard", sku: "USB", on_shelf: "4.000", reserved: "0", selling_price: "100.00", lowest_price: "0.00", buying_price: "40.00" },
];
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : rows));
});

it("works out what is missing and what it is worth, then records sold items as a sale", async () => {
  render(<MemoryRouter><StockCheckPage /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("Counted Normal charger"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Counted USB cable"), { target: { value: "4" } });
  const summary = screen.getByRole("status");
  expect(within(summary).getByText("Items missing").nextSibling).toHaveTextContent("3");
  expect(within(summary).getByText("Worth at selling price").nextSibling).toHaveTextContent("900");
  expect(within(summary).getByText("Worth at your lowest price").nextSibling).toHaveTextContent("750");
  expect(within(summary).getByText("What they cost you").nextSibling).toHaveTextContent("480");
  expect(screen.getByText("Matches")).toBeInTheDocument();
  const settle = screen.getByRole("region", { name: "Differences to record (1)" });
  fireEvent.change(within(settle).getByLabelText(/Price each/), { target: { value: "280" } });
  fireEvent.click(within(settle).getByRole("button", { name: "Record" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/commerce/pos/complete/", expect.objectContaining({ method: "POST" })));
  const body = JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/commerce/pos/complete/")[1].body);
  expect(body).toMatchObject({ items: [{ variant_id: 1, quantity: 3, unit_price: "280" }], payment_method: "CASH" });
});

it("records missing items as lost through the stock check", async () => {
  render(<MemoryRouter><StockCheckPage /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("Counted USB cable"), { target: { value: "3" } });
  const settle = screen.getByRole("region", { name: "Differences to record (1)" });
  fireEvent.change(within(settle).getByLabelText("What happened?"), { target: { value: "lost" } });
  fireEvent.click(within(settle).getByRole("button", { name: "Record" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/inventory/stock-check/", expect.objectContaining({ method: "POST" })));
  expect(JSON.parse(api.mock.calls.find(([p, o]) => p === "/api/v1/inventory/stock-check/" && o)[1].body)).toMatchObject({ variant_id: 2, quantity: 1, kind: "lost" });
});
