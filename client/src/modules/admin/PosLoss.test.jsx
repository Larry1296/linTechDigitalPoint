import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PosPage } from "./AdminPages";
import { api, ApiError } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["commerce.change_sale", "commerce.sell_below_cost", "accounting.view_profit"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));

const router = { id: 7, product_name: "Router", variant_name: "AC1200", sku: "RTR", selling_price: "1000", available: "5", product_type: "STOCK_ITEM", category_name: "Networking" };
beforeEach(() => vi.clearAllMocks());

it("sells at a negotiated price and, after a clear warning, records a below-cost sale as a LOSS", async () => {
  let attempts = 0;
  api.mockImplementation(async (path, options = {}) => {
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return [router];
    if (path === "/api/v1/commerce/pos/complete/") {
      attempts += 1;
      const body = JSON.parse(options.body);
      if (!body.allow_below_cost) throw new ApiError(400, "This sale is below buying cost.", { code: "below_cost", below_cost: ["Router: sold for 400.00 but its recorded cost is 550.00"] });
      return { sale_id: 3, receipt_number: "POS-1", total: "400.00", gross_profit: "-150.00", cost_pending: false };
    }
    return [];
  });
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /Router/ }));
  const cart = screen.getByRole("heading", { name: "Current sale" }).closest("form");
  fireEvent.change(within(cart).getByLabelText(/Agreed price for/), { target: { value: "400" } });
  await act(async () => { fireEvent.click(within(cart).getByRole("button", { name: /^Complete sale/ })); });
  expect(attempts).toBe(2);
  expect(confirmAction).toHaveBeenLastCalledWith(expect.objectContaining({ title: "Sell at a loss?", text: expect.stringContaining("recorded cost is 550.00") }));
  const sent = JSON.parse(api.mock.calls.filter(([p]) => p === "/api/v1/commerce/pos/complete/").at(-1)[1].body);
  expect(sent.items).toEqual([{ variant_id: 7, quantity: 1, unit_price: "400" }]);
  expect(await screen.findByText(/LOSS of/)).toHaveClass("lossText");
});
