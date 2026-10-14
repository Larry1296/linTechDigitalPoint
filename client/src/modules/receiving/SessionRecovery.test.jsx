import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthProvider } from "../../core/auth/AuthContext";
import { ReceivePage } from "./ReceivePage";
import { LoginPage } from "../auth/AuthPages";
import { api, SESSION_EXPIRED_MESSAGE } from "../../core/api/client";
import { StaffProtectedRoute } from "../../routes/ProtectedRoutes";

vi.mock("../../core/api/client", async (original) => ({
  ...(await original()),
  api: vi.fn(),
}));
vi.mock("../../core/cart/CartContext", () => ({
  useCart: () => ({ refreshCart: async () => {} }),
}));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: async () => true }));
const user = { id: 42, username: "staff", authenticated: true, is_staff: true, permissions: [], organization: {id: 7, name: "Test Business", enabled_modules: ["inventory", "locations"]}, memberships: [] };
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
  api.mockImplementation(async (path) => {
    if (path.includes("/auth/")) return user;
    return [];
  });
});
function renderFlow() {
  return render(
    <MemoryRouter initialEntries={["/admin/receive"]}>
      <AuthProvider>
        <Routes>
          <Route
            path="/admin/receive"
            element={
              <StaffProtectedRoute>
                <ReceivePage />
              </StaffProtectedRoute>
            }
          />
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}
it("revisits earlier receipt steps and reviews the amended entries", async () => {
  sessionStorage.setItem(
    "receipt-draft:7:42",
    JSON.stringify({
      version: 1,
      categoryId: "1",
      step: 3,
      details: { supplier_name: "Original supplier", external_reference: "INV-1", notes: "" },
      lines: [
        {
          variant_id: "7",
          received_quantity: "4",
          unit_cost: "100",
          placements: [{ shelf_id: "9", quantity: "4" }],
        },
      ],
    }),
  );
  api.mockImplementation(async (path) => {
    if (path.includes("/auth/")) return user;
    if (path.includes("categories/available"))
      return [{ id: 1, name: "Cables", rack_names: ["Rack 1"] }];
    if (path.includes("locations/zones"))
      return [
        {
          id: 1,
          active: true,
          name: "Shop",
          stacks: [
            {
              id: 1,
              active: true,
              display_name: "Rack 1",
              categories: [{ id: 1 }],
              levels: [
                {
                  id: 1,
                  active: true,
                  level_number: 1,
                  shelves: [
                    {
                      id: 9,
                      active: true,
                      code: "S9",
                      display_name: "Shelf 9",
                    },
                  ],
                },
              ],
            },
          ],
        },
      ];
    if (path.includes("variants/search"))
      return [
        {
          id: 7,
          product_name: "Cable",
          variant_name: "Type-B",
          sku: "TYPE-B",
          category_id: 1,
          selling_price: "200",
        },
      ];
    return [];
  });
  renderFlow();
  fireEvent.click(
    await screen.findByRole("button", { name: "1. Receipt details" }),
  );
  fireEvent.change(await screen.findByRole("textbox", { name: "Supplier name" }), {
    target: { value: "Updated supplier" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "2. Items and placement" }),
  );
  expect(screen.getByLabelText("Received quantity")).toHaveValue(4);
  fireEvent.change(screen.getByLabelText("Buying price per unit"), {
    target: { value: "125" },
  });
  fireEvent.click(screen.getByRole("button", { name: "3. Review" }));
  expect(screen.getByText(/Updated supplier/)).toBeInTheDocument();
  expect(screen.getByText(/Total: 4 units · KSh 500.00/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Back to edit" }));
  fireEvent.change(screen.getByLabelText("Received quantity"), {
    target: { value: "5" },
  });
  fireEvent.click(screen.getByRole("button", { name: "3. Review" }));
  expect(
    screen.getByText(/placement quantities must equal/),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Received quantity")).toHaveValue(5);
});

it("keeps unfinished product creation fields when returning to earlier receipt steps", async () => {
  sessionStorage.setItem(
    "receipt-draft:7:42",
    JSON.stringify({
      version: 1,
      categoryId: "1",
      step: 2,
      details: { supplier_name: "Supplier", external_reference: "INV-2" },
      lines: [
        {
          variant_id: "",
          received_quantity: "4",
          unit_cost: "100",
          placements: [{ shelf_id: "", quantity: "4" }],
        },
      ],
    }),
  );
  renderFlow();
  fireEvent.click(
    await screen.findByRole("button", { name: "+ Create new product" }),
  );
  fireEvent.change(screen.getByLabelText("Product name"), {
    target: { value: "New cable" },
  });
  fireEvent.change(screen.getByLabelText("Barcode"), {
    target: { value: "12345" },
  });
  fireEvent.change(screen.getByLabelText("Selling price"), {
    target: { value: "250" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Back to receipt", exact: true }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Back to receipt details" }),
  );
  fireEvent.change(await screen.findByRole("textbox", { name: "Supplier name" }), {
    target: { value: "Amended supplier" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "2. Items and placement" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "+ Create new product" }));
  expect(screen.getByLabelText("Product name")).toHaveValue("New cable");
  expect(screen.getByLabelText("Barcode")).toHaveValue("12345");
  expect(screen.getByLabelText("Selling price")).toHaveValue(250);
  fireEvent.change(screen.getByLabelText("Product name"), {
    target: { value: "Corrected cable" },
  });
  expect(screen.getByLabelText("Product name")).toHaveValue("Corrected cable");
});
it("keeps unsaved edits behind the password unlock overlay", async () => {
  renderFlow();
  fireEvent.change(await screen.findByRole("textbox", { name: "Supplier name" }), {
    target: { value: "Cable supplier" },
  });
  fireEvent.change(screen.getByLabelText("General notes"), {
    target: { value: "Unfinished delivery" },
  });
  const saved = JSON.parse(sessionStorage.getItem("receipt-draft:7:42"));
  expect(saved.details.supplier_name).toBe("Cable supplier");
  act(() => window.dispatchEvent(new CustomEvent("session-locked")));
  expect(await screen.findByRole("dialog")).toHaveTextContent(SESSION_EXPIRED_MESSAGE);
  expect(screen.queryByLabelText("Username or email")).not.toBeInTheDocument();
  // Filled in one go (as a saved or pasted password is), so it unlocks by itself, without pressing Unlock.
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), {
    target: { value: "password" },
  });
  expect(await screen.findByRole("textbox", { name: "Supplier name" })).toHaveValue(
    "Cable supplier",
  );
  expect(screen.getByLabelText("General notes")).toHaveValue(
    "Unfinished delivery",
  );
  expect(
    JSON.parse(sessionStorage.getItem("receipt-draft:7:42")).idempotencyKey,
  ).toBe(saved.idempotencyKey);
});
it("restores review lines and placements, then clears a successfully submitted draft", async () => {
  const draft = {
    version: 1,
    categoryId: "1",
    step: 3,
    idempotencyKey: "receipt-retry-key",
    details: { supplier_name: "Supplier", external_reference: "INV-3", notes: "Keep dry" },
    lines: [
      {
        variant_id: "7",
        received_quantity: "4",
        unit_cost: "100",
        update_selling_price: true,
        new_selling_price: "200",
        placements: [{ shelf_id: "9", quantity: "4" }],
      },
    ],
  };
  sessionStorage.setItem("receipt-draft:7:42", JSON.stringify(draft));
  api.mockImplementation(async (path, options) => {
    if (path.includes("/auth/")) return user;
    if (options?.method === "POST")
      return {
        receipt_number: "REC-1",
        lines: [{ quantity: 4, line_cost: 400 }],
      };
    return [];
  });
  renderFlow();
  fireEvent.click(
    await screen.findByRole("button", { name: "Complete receipt" }),
  );
  await screen.findByText("REC-1");
  const [, options] = api.mock.calls.find(
    ([, options]) => options?.method === "POST",
  );
  expect(JSON.parse(options.body)).toEqual({
    ...draft.details,
    document_status: "SUPPLIER_DOCUMENT",
    landed_costs: [],
    lines: draft.lines,
    idempotency_key: draft.idempotencyKey,
  });
  await waitFor(() =>
    expect(sessionStorage.getItem("receipt-draft:7:42")).toBeNull(),
  );
});
