import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { QuickReceivePage } from "./QuickReceivePage";
import { api } from "../../core/api/client";

const DEFAULTS = {
  item: { id: 9, product_name: "TECNO SPARK 40 HARD COVER (MEN)", variant_name: "HARD (MEN)", sku: "TEC-SP40-HARD-M", available: "1.000", pack_size: 1 },
  supplier_name: "Luthuli Covers", unit_cost: "120.00", document_status: "NO_DOCUMENT", payment_method: "CASH",
  shelf: { id: 31, code: "LEFTWALL-R01-L03-S02", display_name: "Left wall level 3 compartment 2" },
};
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [] } }) }));
beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (url) => (url.includes("receive-defaults") ? DEFAULTS : { id: 4, receipt_number: "RCV-1" }));
});
const open = async () => {
  await act(async () => { render(<MemoryRouter initialEntries={["/admin/quick-receive?variant=9"]}><QuickReceivePage /></MemoryRouter>); });
};

it("from a product page asks only how many arrived and repeats the last delivery", async () => {
  await open();
  expect(api).toHaveBeenCalledWith("/api/v1/inventory/variants/9/receive-defaults/");
  expect(screen.getByText(/As last time/)).toHaveTextContent("Luthuli Covers");
  expect(screen.queryByLabelText("Supplier")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/Buying price/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Quantity received"), { target: { value: "3" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Receive stock" })); });
  const body = JSON.parse(api.mock.calls.at(-1)[1].body);
  expect(body).toMatchObject({ supplier_name: "Luthuli Covers", document_status: "NO_DOCUMENT", payment: { method: "CASH", amount: "360" },
    lines: [{ variant_id: 9, received_quantity: "3", unit_cost: "120", placements: [{ shelf_id: 31, quantity: "3" }] }] });
});

it("shows every field after Change", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Change" }));
  expect(screen.getByLabelText("Supplier")).toHaveValue("Luthuli Covers");
  expect(screen.getByLabelText("Buying price for one")).toHaveValue(120);
});

it("asks for the supplier too when none was recorded (an imported item)", async () => {
  api.mockImplementation(async () => ({ ...DEFAULTS, supplier_name: "", payment_method: "" }));
  await open();
  expect(screen.getByText(/As last time/)).toHaveTextContent("owed to the supplier");
  expect(screen.getByLabelText("Supplier")).toHaveValue("");
  expect(screen.queryByLabelText(/Buying price/)).not.toBeInTheDocument();
});

it("asks for everything when nothing is known about the item", async () => {
  api.mockImplementation(async () => ({ ...DEFAULTS, supplier_name: "", unit_cost: null, shelf: null, payment_method: "" }));
  await open();
  expect(screen.queryByText(/As last time/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("Buying price for one")).toHaveValue(null);
});
