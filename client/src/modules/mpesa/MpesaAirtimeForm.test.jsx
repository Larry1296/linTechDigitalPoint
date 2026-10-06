import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MpesaAirtimeForm } from "./MpesaAirtimeForm";
import { CustomerTransactionList } from "./CustomerTransactionList";
import { postMpesaTransaction } from "./api";
vi.mock("./api", () => ({ postMpesaTransaction: vi.fn(), addMpesaReference: vi.fn(), correctMpesaTransaction: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [] } }) }));
beforeEach(() => {
  vi.clearAllMocks();
  postMpesaTransaction.mockResolvedValue({ amount: "100.00", customer_phone: "254712345678", paid_by: "MPESA_OTHER" });
});

const after = (label) => screen.getByLabelText(`${label} after`).textContent;

it("records airtime with how the customer paid, showing what it does to cash and float", async () => {
  const posted = vi.fn();
  render(<MpesaAirtimeForm sessionId={4} availableCash="2000" availableFloat="3000" onPosted={posted} />);
  fireEvent.change(screen.getByLabelText(/Number the airtime was sent to/), { target: { value: "0712345678" } });
  fireEvent.change(screen.getByLabelText("Amount (KSh)"), { target: { value: "100" } });
  expect([after("Cash"), after("Float")]).toEqual(["2,100", "2,900"]);  // cash by default
  fireEvent.click(screen.getByLabelText(/M-Pesa to this agent line/));
  expect([after("Cash"), after("Float")]).toEqual(["2,000", "3,000"]);
  fireEvent.click(screen.getByLabelText(/M-Pesa to another number/));
  expect([after("Cash"), after("Float")]).toEqual(["2,000", "2,900"]);
  fireEvent.click(screen.getByRole("button", { name: "Record airtime" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(postMpesaTransaction).toHaveBeenCalledWith(expect.objectContaining({ session: 4, transaction_type: "AIRTIME_SALE", amount: "100",
    paid_by: "MPESA_OTHER", customer_phone: "0712345678" }));
  expect(screen.getByText(/Recorded airtime of KSh 100 to 0712 345 678, paid by m-pesa to another number/)).toBeInTheDocument();
});

it("lists airtime sold apart from deposits and withdrawals", () => {
  const rows = [
    { id: 1, transaction_type: "AIRTIME_SALE", amount: "100", customer_phone: "254712345678", paid_by: "CASH", occurred_at: "2026-10-06T09:00:00Z", provider_reference: "SK1" },
    { id: 2, transaction_type: "CUSTOMER_DEPOSIT", amount: "500", customer_phone: "", occurred_at: "2026-10-06T09:05:00Z", provider_reference: "SK2" },
  ];
  render(<CustomerTransactionList title="Airtime sold" type="AIRTIME_SALE" transactions={rows} onChanged={vi.fn()} />);
  const table = screen.getByRole("table", { name: "Airtime sold this shift" });
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(within(table).getByText("0712 345 678")).toBeInTheDocument();
  expect(within(table).getByText("Cash")).toBeInTheDocument();
  expect(screen.getByText("Total KSh 100.")).toBeInTheDocument();
});
