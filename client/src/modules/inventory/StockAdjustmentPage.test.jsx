import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { StockAdjustmentPage } from "./StockAdjustmentPage";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";
const auth = vi.hoisted(() => ({ user: { is_superuser: true } }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn() }));
const context = {
  display_name: "Amaya — AM-M01 Type-B (Micro-USB)",
  sku: "TYPE-B",
  lots: [{ id: 1, reference: "147" }],
  balances: [{ shelf_id: 1, lot_id: 1, quantity: "2.000", reserved: "0.000" }],
  history: [],
};
const zones = [
  {
    id: 1,
    active: true,
    name: "Zone A",
    stacks: [
      {
        id: 1,
        active: true,
        display_name: "Rack",
        levels: [
          {
            id: 1,
            active: true,
            level_number: 1,
            shelves: [
              {
                id: 1,
                active: true,
                physical_label: "AL1C1S1",
                display_name: "Compartment 1",
              },
            ],
          },
        ],
      },
    ],
  },
];
beforeEach(() => {
  vi.clearAllMocks();
  auth.user = { is_superuser: true };
  confirmAction.mockResolvedValue(true);
  api.mockImplementation(async (url, options) => {
    if (options?.method === "POST")
      return {
        id: 1,
        quantity_after: JSON.parse(options.body).counted_quantity,
      };
    if (url.includes("variants/search"))
      return [
        {
          id: 1,
          product_name: "Amaya",
          variant_name: "Type-B (Micro-USB)",
          sku: "TYPE-B",
        },
      ];
    if (url.includes("adjustments/variants")) return context;
    if (url.includes("zones")) return zones;
    return [];
  });
});
async function form(count = "4") {
  render(
    <MemoryRouter initialEntries={["/admin-app/adjust-stock?variant=1"]}>
      <StockAdjustmentPage />
    </MemoryRouter>,
  );
  await screen.findByRole("option", { name: "AL1C1S1 — Compartment 1" });
  fireEvent.change(screen.getByLabelText("Compartment"), {
    target: { value: "1" },
  });
  fireEvent.change(await screen.findByLabelText("Physical counted quantity"), {
    target: { value: count },
  });
  fireEvent.change(screen.getByLabelText("Reason"), {
    target: { value: "Opening stock correction" },
  });
}
it("confirms an exact variant increase and shows the posted result", async () => {
  await form();
  expect(screen.getByText("Adjustment: +2")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Review and post adjustment" }),
  );
  await screen.findByText("Adjustment #1 posted. Quantity: 4.");
  expect(confirmAction).toHaveBeenCalledWith(
    expect.objectContaining({ text: expect.stringContaining("Type-B") }),
  );
  const [, options] = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(JSON.parse(options.body)).toMatchObject({
    variant_id: 1,
    shelf_id: 1,
    lot_id: 1,
    expected_quantity: 2,
    counted_quantity: "4",
    confirmed: true,
    reason: "Opening stock correction",
  });
});
it("calculates decreases and does not post when confirmation is cancelled", async () => {
  confirmAction.mockResolvedValue(false);
  await form("1");
  expect(screen.getByText("Adjustment: -1")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Review and post adjustment" }),
  );
  await waitFor(() => expect(confirmAction).toHaveBeenCalled());
  expect(api.mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
});
it("blocks negative counts and requires a reason", async () => {
  await form("-1");
  expect(
    screen.getByRole("button", { name: "Review and post adjustment" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Physical counted quantity"), {
    target: { value: "4" },
  });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "" } });
  expect(
    screen.getByRole("button", { name: "Review and post adjustment" }),
  ).toBeDisabled();
});
it("keeps the count after rejection and reports the server conflict", async () => {
  const original = api.getMockImplementation();
  api.mockImplementation((url, options) =>
    options?.method === "POST"
      ? Promise.reject(new Error("Stock changed; refresh and recount."))
      : original(url, options),
  );
  await form();
  fireEvent.click(
    screen.getByRole("button", { name: "Review and post adjustment" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Stock changed");
  expect(screen.getByLabelText("Physical counted quantity")).toHaveValue(4);
  expect(screen.queryByText(/Adjustment #1 posted/)).not.toBeInTheDocument();
});
it("denies unauthorized staff without fetching stock", () => {
  auth.user = { permissions: [] };
  render(
    <MemoryRouter>
      <StockAdjustmentPage />
    </MemoryRouter>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("permission is required");
  expect(api).not.toHaveBeenCalled();
});
it("displays adjustment audit history", async () => {
  const original = api.getMockImplementation();
  api.mockImplementation((url, options) =>
    url.includes("adjustments/variants")
      ? Promise.resolve({
          ...context,
          history: [
            {
              id: 1,
              adjustment_id: 1,
              movement_type: "STOCK_ADJUSTMENT",
              shelf: "AL1C1S1",
              lot_id: 1,
              quantity: "2",
              quantity_before: "2",
              quantity_after: "4",
              reason: "Opening stock correction",
              notes: "Physical recount",
              administrator: "owner",
              created_at: "2026-09-09T12:00:00Z",
            },
          ],
        })
      : original(url, options),
  );
  await form();
  expect(
    screen.getByText(/STOCK_ADJUSTMENT · AL1C1S1 · Lot 1/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Physical recount · · owner/)).toBeInTheDocument();
});
