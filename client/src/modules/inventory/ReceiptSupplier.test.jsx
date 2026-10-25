import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ReceiptSupplier } from "./ReceiptSupplier";
import { api } from "../../core/api/client";
import { askForm, confirmAction } from "../../core/ui/alerts";

vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { is_superuser: true, permissions: [] } }) }));
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(), askForm: vi.fn() }));

const supplier = { supplier: "LYCOM MOBILE ACCESSORIES", amount: "760.00", returned: "0", paid: "0", owed: "760.00",
  already_owned: false, can_mark_already_owned: true, payments: [] };
const receipt = { id: 9, receipt_number: "RCV-261014-469F305A", received_at: "2026-10-14T09:00:00Z", supplier };
const can = { pay: true, undo: true, markOwned: true };

beforeEach(() => {
  vi.clearAllMocks();
  confirmAction.mockResolvedValue(true);
});

it("shows what is owed and records a payment on the day it was paid, from where the money came from", async () => {
  const onSaved = vi.fn();
  api.mockResolvedValue({ ...receipt, supplier: { ...supplier, paid: "760.00", owed: "0.00" } });
  render(<ReceiptSupplier receipt={receipt} can={can} onSaved={onSaved} />);
  expect(screen.getByText("still owed KSh 760")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "I paid LYCOM MOBILE ACCESSORIES" }));
  expect(screen.getByLabelText("Amount paid (KSh)")).toHaveValue(760);
  fireEvent.change(screen.getByLabelText("Date paid"), { target: { value: "2026-10-14" } });
  fireEvent.change(screen.getByLabelText("Where the money came from"), { target: { value: "OWNER" } });
  fireEvent.click(screen.getByRole("button", { name: "Review payment" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(confirmAction.mock.calls[0][0].text).toMatch(/drawer, till and bank stay as they are/);
  const [url, options] = api.mock.calls.at(-1);
  expect(url).toBe("/api/v1/inventory/receipts/9/pay-supplier/");
  expect(JSON.parse(options.body)).toMatchObject({ amount: "760", source: "OWNER", paid_on: "2026-10-14" });
  expect(onSaved.mock.calls[0][1]).toMatch(/Nothing is owed to LYCOM/);
});

it("marks stock that was already owned as opening stock after confirming", async () => {
  const onSaved = vi.fn();
  api.mockResolvedValue({ ...receipt, supplier: { ...supplier, owed: "0", already_owned: true } });
  render(<ReceiptSupplier receipt={receipt} can={can} onSaved={onSaved} />);
  fireEvent.click(screen.getByRole("button", { name: "This stock was already mine" }));
  fireEvent.click(screen.getByRole("button", { name: "Review" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(confirmAction.mock.calls[0][0].text).toMatch(/stay exactly as they are/);
  expect(api.mock.calls[0][0]).toBe("/api/v1/inventory/receipts/9/already-owned/");
});

it("lists payments with an undo, and offers no fix when nothing is owed", async () => {
  const paid = { ...supplier, paid: "760.00", owed: "0.00", can_mark_already_owned: false,
    payments: [{ id: 41, amount: "760.00", paid_on: "2026-10-14", source: "CASH", source_label: "Shop cash drawer", undone: false }] };
  askForm.mockResolvedValue({ reason: "Entered twice" });
  api.mockResolvedValue({ ...receipt, supplier });
  const onSaved = vi.fn();
  render(<ReceiptSupplier receipt={{ ...receipt, supplier: paid }} can={can} onSaved={onSaved} />);
  expect(screen.getByText("nothing owed")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /I paid/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(api.mock.calls[0][0]).toBe("/api/v1/inventory/receipts/9/payments/41/undo/");
});

it("says plainly when the receipt is already opening stock", () => {
  render(<ReceiptSupplier receipt={{ ...receipt, supplier: { ...supplier, owed: "0", already_owned: true } }} can={can} onSaved={vi.fn()} />);
  expect(screen.getByText(/Nothing is owed to LYCOM MOBILE ACCESSORIES for it/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "It was a purchase after all" })).toBeInTheDocument();
});
