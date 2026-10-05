import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["commerce.add_payment", "commerce.change_payment", "accounting.reverse_cashentry"] } }) }));
import { api } from "../../core/api/client";
import { SalesPage } from "./SalesPage";

// The real case: M-Pesa 250 left waiting, then the same 250 recorded again as cash.
const earphones = { id: 5, number: "POS-E400BA491A", created_at: "2026-10-01T01:45:00Z", customer: "Walk-in", status: "COMPLETED", due_date: null,
  total: "250.00", charged: "250.00", outstanding: "0.00",
  payments: [{ id: 51, method: "MPESA", amount: "250.00", status: "MANUAL_REVIEW" }, { id: 52, method: "CASH", amount: "250.00", status: "COMPLETED" }],
  items: [{ id: 5, item: "ORAIMO ORIGINAL EARPHONES — ORIGINAL", quantity: "1.000", list_price: "300.00", unit_price: "250.00", discount: "0", returned_quantity: "0" }] };

it("explains a sale paid twice instead of offering a confirmation that must fail, and can delete the duplicate M-Pesa", async () => {
  let dropped = false;
  api.mockImplementation(async (path) => {
    if (path.includes("/payments/51/delete/")) { dropped = true; return { id: 51, status: "FAILED" }; }
    return { count: 1, results: [dropped ? { ...earphones, payments: [{ ...earphones.payments[0], status: "FAILED" }, earphones.payments[1]] } : earphones] };
  });
  render(<SalesPage />);
  const row = (await screen.findByText("ORAIMO ORIGINAL EARPHONES")).closest("details");
  expect(row.querySelector("summary")).toHaveTextContent("Paid twice? Check payments");
  expect(within(row).getByText(/already paid by the other payment here \(Cash KSh 250\)/)).toBeInTheDocument();
  expect(within(row).queryByRole("button", { name: "Confirm money received" })).toBeNull();
  const mpesa = within(row).getAllByText("Delete this payment")[0].closest("details");
  fireEvent.change(within(mpesa).getByLabelText("Reason"), { target: { value: "Same money as the cash" } });
  await act(async () => { fireEvent.click(within(mpesa).getByRole("button", { name: "Delete payment" })); });
  const call = api.mock.calls.find(([p]) => p === "/api/v1/commerce/payments/51/delete/");
  expect(JSON.parse(call[1].body)).toEqual({ reason: "Same money as the cash" });
  expect(await screen.findByText("Payment of KSh 250 deleted. POS-E400BA491A now shows what is owed.")).toBeInTheDocument();
  expect(row.querySelector("summary")).toHaveTextContent("Paid");
});

it("warns before recording money that may be the waiting M-Pesa", async () => {
  api.mockResolvedValue({ count: 1, results: [{ ...earphones, outstanding: "250.00", payments: [earphones.payments[0]] }] });
  render(<SalesPage />);
  const row = (await screen.findByText("ORAIMO ORIGINAL EARPHONES")).closest("details");
  expect(within(row).getByText(/still waiting for confirmation/)).toBeInTheDocument();
  expect(within(row).getByRole("button", { name: "Confirm money received" })).toBeInTheDocument();
});
