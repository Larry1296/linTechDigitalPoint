import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["mpesa.reverse_mpesa_transaction"] } }) }));
vi.mock("./api", () => ({ getPastMpesaShifts: vi.fn(), getMpesaShiftTransactions: vi.fn(), addMpesaReference: vi.fn() }));
import * as api from "./api";
import { PastShifts } from "./PastShifts";

const shift = { id: 7, outlet: "Main till", operator: "Jane", opened_at: "2026-10-03T05:02:00Z", closed_at: "2026-10-03T15:30:00Z", records: 2,
  opening_cash: "1000.00", opening_float: "5000.00", closing_cash: "1500.00", closing_float: "4500.00", cash_variance: "0.00", float_variance: "0.00" };
const deposit = { id: 1, session: 7, transaction_type: "CUSTOMER_DEPOSIT", amount: "500.00", occurred_at: "2026-10-03T06:00:00Z",
  customer_phone: "254712345678", customer_id_number: "12345678", provider_reference: "ABC123", cash_delta: "500.00", float_delta: "-500.00" };
const topUp = { id: 2, session: 7, transaction_type: "FLOAT_TOPUP", amount: "300.00", occurred_at: "2026-10-03T07:00:00Z",
  internal_reference: "MP-2", cash_delta: "-300.00", float_delta: "300.00" };

it("lists closed shifts by when they ran and opens just the picked shift's records, without corrections", async () => {
  api.getPastMpesaShifts.mockResolvedValue([shift]);
  api.getMpesaShiftTransactions.mockResolvedValue([deposit, topUp]);
  render(<PastShifts />);
  fireEvent.click(screen.getByRole("button", { name: "Look at a past shift" }));
  const option = await screen.findByRole("option", { name: /Sat.*3.*2026.*08:02.*(18:30|06:30 PM).*Main till.*Jane \(2 records\)/ });
  fireEvent.change(screen.getByLabelText("Shift"), { target: { value: String(shift.id) } });
  expect(api.getMpesaShiftTransactions).toHaveBeenCalledWith(String(option.value));
  const deposits = await screen.findByRole("table", { name: "Deposits in that shift" });
  expect(deposits).toHaveTextContent("0712 345 678");
  expect(within(deposits).queryByRole("button", { name: /correct/i })).toBeNull();
  expect(screen.getByRole("table", { name: "Other movements in that shift" })).toHaveTextContent("float topup");
  expect(screen.getByText(/Closed with cash .*1,500.00.*as expected/)).toBeInTheDocument();
});

it("says so when no closed shift has records", async () => {
  api.getPastMpesaShifts.mockResolvedValue([]);
  render(<PastShifts />);
  fireEvent.click(screen.getByRole("button", { name: "Look at a past shift" }));
  expect(await screen.findByText("No closed shift has records yet.")).toBeInTheDocument();
});

it("shows the commission each past shift earned, in the list and for the picked shift", async () => {
  api.getPastMpesaShifts.mockResolvedValue([{ ...shift, commission: { earned: "86.00", measured: 2, learned: 1, unknown: 1 } }]);
  api.getMpesaShiftTransactions.mockResolvedValue([deposit]);
  render(<PastShifts />);
  fireEvent.click(screen.getByRole("button", { name: "Look at a past shift" }));
  await screen.findByRole("option", { name: /Jane \(2 records\) · commission .*86\.00/ });
  fireEvent.change(screen.getByLabelText("Shift"), { target: { value: String(shift.id) } });
  expect(screen.getByText(/Commission earned in this shift/)).toHaveTextContent(/86\.00.*1 transaction not worked out yet/);
});
