import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [
  "accounting.view_loan", "accounting.add_loan", "accounting.add_loanrepayment", "accounting.reverse_cashentry"] } }) }));
import { api } from "../../core/api/client";
import { MoneyLentPage } from "./MoneyLentPage";

const loan = (id, name, extra = {}) => ({ id, borrower_name: name, borrower_phone: "0712345678", amount: "5000.00", method: "CASH",
  lent_on: "2026-09-01", due_date: "2026-10-15", notes: "", repaid: "0.00", outstanding: "5000.00", status: "OUTSTANDING",
  days_overdue: 0, recorded_by: "Owner", cancelled_at: null, cancel_reason: "", repayments: [], ...extra });

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : {
    loans: [loan(1, "Mary Achieng"), loan(2, "Tom Kip", { status: "OVERDUE", days_overdue: 3, due_date: "2026-09-23" }),
      loan(3, "Ann Wairimu", { status: "REPAID", repaid: "5000.00", outstanding: "0.00",
        repayments: [{ id: 9, amount: "5000.00", method: "MPESA", reference: "SJK4ABC123", received_on: "2026-09-20", recorded_by: "Owner", reversed_at: null }] })],
    total_outstanding: "10000.00", overdue: 1 }));
});

it("lists what is still owed, overdue first, and keeps repaid loans aside", async () => {
  render(<MoneyLentPage />);
  const owed = await screen.findByRole("region", { name: "Still owed (2)" });
  expect(within(owed).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Tom Kip", "Mary Achieng"]);
  expect(within(owed).getByText(/Overdue · 3 days late/)).toBeInTheDocument();
  expect(screen.getByText(/Still owed to you/)).toHaveTextContent("10,000");
  expect(within(owed).queryByText("Ann Wairimu")).not.toBeInTheDocument();
  expect(screen.getByText("Repaid and cancelled (1)")).toBeInTheDocument();
});

it("records a loan with its agreed payback date", async () => {
  render(<MoneyLentPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Lend money" }));
  const fill = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fill("Borrower's name", "Jane Wanjiru");
  fill("Amount (KSh)", "3000");
  fill("Agreed payback date", "2026-12-01");
  fireEvent.click(screen.getByRole("button", { name: "Record loan" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/accounting/loans/", expect.objectContaining({ method: "POST" })));
  const body = JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body);
  expect(body).toMatchObject({ borrower_name: "Jane Wanjiru", amount: "3000", method: "CASH", due_date: "2026-12-01" });
});

it("confirms a repayment, asking for the M-Pesa code when paid by M-Pesa", async () => {
  render(<MoneyLentPage />);
  const mary = (await screen.findByRole("heading", { name: "Mary Achieng" })).closest("li");
  fireEvent.click(within(mary).getByRole("button", { name: "Record repayment" }));
  expect(within(mary).getByLabelText(/Amount paid back/)).toHaveValue(5000);
  fireEvent.change(within(mary).getByLabelText("Received by"), { target: { value: "MPESA" } });
  expect(within(mary).getByLabelText("M-Pesa code")).toBeRequired();
  fireEvent.change(within(mary).getByLabelText("M-Pesa code"), { target: { value: "QWE123RTY" } });
  fireEvent.click(within(mary).getByRole("button", { name: "Confirm money received" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/accounting/loans/1/repay/", expect.objectContaining({ method: "POST" })));
});
