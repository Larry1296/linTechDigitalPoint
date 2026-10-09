import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("./api", () => ({ addMpesaReference: vi.fn(async () => ({})), correctMpesaTransaction: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [] } }) }));
import { addMpesaReference } from "./api";
import { CustomerTransactionList, localPhone } from "./CustomerTransactionList";

const now = new Date().toISOString();
const deposit = (id, name, extra = {}) => ({ id, transaction_type: "CUSTOMER_DEPOSIT", occurred_at: now, amount: "2500.00", customer_name: name,
  customer_phone: "254712345678", customer_id_number: "12345678", provider_reference: null, reversal_of: null, ...extra });

it("lists today's deposits with number and ID, and the transaction ID is added afterwards", async () => {
  const changed = vi.fn();
  render(<CustomerTransactionList title="Deposits" type="CUSTOMER_DEPOSIT" onChanged={changed} transactions={[
    deposit(2, ""),
    deposit(1, "", { provider_reference: "SJK4ABC123" }),
    { ...deposit(3, ""), transaction_type: "CUSTOMER_WITHDRAWAL" },
  ]} />);
  expect(screen.getByRole("heading", { name: "Deposits this shift (2)" })).toBeInTheDocument();
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("0712 345 678");
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("12345678");
  expect(screen.getByText("SJK4ABC123")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add transaction ID" }));
  fireEvent.change(screen.getByLabelText(/Transaction ID for the 2,500/), { target: { value: "QWE123RTY" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(changed).toHaveBeenCalled());
  expect(addMpesaReference).toHaveBeenCalledWith(2, "QWE123RTY");
});

it("lists withdrawals by time, amount and the commission balance read after each", () => {
  render(<CustomerTransactionList title="Withdrawals" type="CUSTOMER_WITHDRAWAL" onChanged={vi.fn()} transactions={[
    { ...deposit(4, ""), transaction_type: "CUSTOMER_WITHDRAWAL", customer_phone: "", customer_id_number: "" }]} />);
  expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Time", "Amount", "Commission balance", "Earned", "Transaction ID"]);
});

it("shows numbers the way customers say them", () => {
  expect(localPhone("254110000000")).toBe("0110 000 000");
});

it("shows what each transaction earned, marking what the app worked out itself", () => {
  render(<CustomerTransactionList title="Withdrawals" type="CUSTOMER_WITHDRAWAL" onChanged={vi.fn()} transactions={[
    { ...deposit(5, "A1"), transaction_type: "CUSTOMER_WITHDRAWAL", commission_balance: "118.00", commission_earned: "18.00", commission_source: "measured" },
    { ...deposit(6, "A2"), transaction_type: "CUSTOMER_WITHDRAWAL", commission_balance: null, commission_earned: "18.00", commission_source: "learned" },
    { ...deposit(7, "A3"), transaction_type: "CUSTOMER_WITHDRAWAL", commission_balance: null, commission_earned: null, commission_source: null }]} />);
  const earned = screen.getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("cell")[2].textContent);
  expect(earned).toEqual(["18", "≈ 18", "—"]);
});
