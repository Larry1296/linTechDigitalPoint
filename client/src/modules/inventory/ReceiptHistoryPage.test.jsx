import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ReceiptHistoryPage } from "./ReceiptHistoryPage";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";

const auth = vi.hoisted(() => ({ user: { is_superuser: true } }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn() }));
const reason =
  "Amaya 10W wall-charger buying price was mistakenly entered against the cable.";
const line = {
  id: 22,
  variant_id: 7,
  product_name: "Amaya charging cable",
  variant_name: "White",
  sku: "CABLE",
  quantity: "3.000",
  unit_cost: "160.00",
  line_cost: "480.00",
  updated_at: "2026-09-11T09:00:00Z",
  placements: [{ shelf_id: 1, code: "A1", quantity: "3.000" }],
  corrections: [],
};
const receipt = {
  id: 145,
  receipt_number: "REC-145",
  supplier_name: "Supplier",
  received_at: "2026-09-11T09:00:00Z",
  lines: [line],
};
beforeEach(() => {
  vi.clearAllMocks();
  auth.user = { is_superuser: true };
  confirmAction.mockResolvedValue(true);
  api.mockImplementation(async (url, options) => {
    if (options?.method === "POST")
      return {
        ...receipt,
        lines: [
          {
            ...line,
            unit_cost: "80.00",
            line_cost: "240.00",
            corrections: [
              {
                id: 1,
                administrator: "admin",
                created_at: receipt.received_at,
                reason,
                before: { ...line, line_total: "480.00" },
                after: { ...line, unit_cost: "80.00", line_total: "240.00" },
              },
            ],
          },
        ],
      };
    if (url.includes("variants/search"))
      return [
        { id: 7, ...line },
        {
          id: 8,
          product_name: "Amaya charging cable",
          variant_name: "Black",
          sku: "BLACK",
        },
      ];
    if (url.endsWith("receipts/"))
      return [{ ...receipt, line_count: 1, total_units: "3.000" }];
    return receipt;
  });
});
function setup(path = "/admin-app/receipts/145") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin-app/receipts" element={<ReceiptHistoryPage />} />
        <Route
          path="/admin-app/receipts/:id"
          element={<ReceiptHistoryPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}
async function form() {
  setup();
  fireEvent.click(
    await screen.findByRole("button", { name: "Correct receipt line" }),
  );
  fireEvent.change(screen.getByLabelText("Buying price per unit (KSh)"), {
    target: { value: "80" },
  });
  fireEvent.change(screen.getByLabelText("Correction reason"), {
    target: { value: reason },
  });
}
it("opens receipt history and its selected receipt", async () => {
  setup("/admin-app/receipts");
  fireEvent.click(
    await screen.findByRole("link", { name: "Receipt 145 · REC-145" }),
  );
  expect(
    await screen.findByRole("button", { name: "Correct receipt line" }),
  ).toBeVisible();
});
it("requires reason, reviews old/new values, confirms 3 × 80 and shows immutable history", async () => {
  await form();
  expect(screen.queryByLabelText("Received quantity")).not.toBeInTheDocument();
  const comparison = screen.getByRole("table");
  expect(within(comparison).getByText("KSh 480.00")).toBeVisible();
  expect(within(comparison).getByText("KSh 240.00")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Review correction" }));
  await screen.findByText(
    "Receipt line corrected. The permanent audit record is shown below.",
  );
  expect(confirmAction).toHaveBeenCalledWith(
    expect.objectContaining({
      text: expect.stringContaining("Quantity: 3 → 3"),
    }),
  );
  const [url, options] = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(url).toBe("/api/v1/inventory/receipts/145/lines/22/correct/");
  expect(JSON.parse(options.body)).toEqual({
    variant_id: 7,
    unit_cost: "80",
    received_quantity: "3.000",
    reason,
    confirmed: true,
    expected_updated_at: line.updated_at,
  });
  expect(
    screen.getByRole("heading", { name: "Correction history" }),
  ).toBeVisible();
});
it("does not post when confirmation is cancelled", async () => {
  confirmAction.mockResolvedValue(false);
  await form();
  fireEvent.click(screen.getByRole("button", { name: "Review correction" }));
  await waitFor(() => expect(confirmAction).toHaveBeenCalled());
  expect(api.mock.calls.some(([, o]) => o?.method === "POST")).toBe(false);
});
it("requires a nonblank reason", async () => {
  await form();
  fireEvent.change(screen.getByLabelText("Correction reason"), {
    target: { value: " " },
  });
  expect(
    screen.getByRole("button", { name: "Review correction" }),
  ).toBeDisabled();
});
it("supports variant selection and explicitly enabled quantity correction", async () => {
  await form();
  await screen.findByRole("option", {
    name: "Amaya charging cable — Black · BLACK",
  });
  fireEvent.change(screen.getByLabelText("Selected product variant"), {
    target: { value: "8" },
  });
  fireEvent.click(
    screen.getByLabelText("Correct received quantity (only if necessary)"),
  );
  fireEvent.change(screen.getByLabelText("Received quantity"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Review correction" }));
  await waitFor(() =>
    expect(api.mock.calls.some(([, o]) => o?.method === "POST")).toBe(true),
  );
  expect(
    JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body),
  ).toMatchObject({ variant_id: 8, received_quantity: "2" });
});
it("shows reversal/stale errors and keeps the review open", async () => {
  await form();
  const original = api.getMockImplementation();
  api.mockImplementation((url, options) =>
    options?.method === "POST"
      ? Promise.reject(new Error("A reversal workflow is required."))
      : original(url, options),
  );
  fireEvent.click(screen.getByRole("button", { name: "Review correction" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "A reversal workflow is required.",
  );
  expect(screen.getByLabelText("Buying price per unit (KSh)")).toHaveValue(80);
});
it("hides correction controls without change receipt permission", async () => {
  auth.user = { permissions: ["inventory.view_stockreceipt"] };
  setup();
  await screen.findByRole("heading", { name: /Receipt 145/ });
  expect(
    screen.queryByRole("button", { name: "Correct receipt line" }),
  ).not.toBeInTheDocument();
});
it("does not load receipts without view permission", () => {
  auth.user = { permissions: [] };
  setup();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Receipt history permission",
  );
  expect(api).not.toHaveBeenCalled();
});
