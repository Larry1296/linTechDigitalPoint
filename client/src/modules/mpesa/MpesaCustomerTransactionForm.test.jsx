import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MpesaDepositForm } from "./MpesaDepositForm";
import { MpesaWithdrawalForm } from "./MpesaWithdrawalForm";
import { lookupMpesaCustomer, postMpesaTransaction } from "./api";
import { confirmAction } from "../../core/ui/alerts";
vi.mock("./api", () => ({ postMpesaTransaction: vi.fn(), lookupMpesaCustomer: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  lookupMpesaCustomer.mockResolvedValue({ found: false });
  postMpesaTransaction.mockResolvedValue({ internal_reference: "MP-1", customer_phone: "254712345678", amount: "100.00", provider_reference: null });
});

const fill = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

it("records a deposit straight away, with no confirmation pop-up", async () => {
  const posted = vi.fn();
  render(<MpesaDepositForm sessionId={4} onPosted={posted} />);
  fill("M-Pesa phone number (optional)", "0712345678");
  fill("ID or passport number (optional)", "12345678");
  fill("Amount (KSh)", "100");
  fireEvent.click(screen.getByRole("button", { name: "Record deposit" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(confirmAction).not.toHaveBeenCalled();
  expect(postMpesaTransaction).toHaveBeenCalledWith({ session: 4, transaction_type: "CUSTOMER_DEPOSIT", amount: "100",
    customer_phone: "0712345678", customer_id_number: "12345678", idempotency_key: expect.any(String) });
  expect(screen.getByLabelText("M-Pesa phone number (optional)")).toHaveValue("");
  expect(screen.getByText(/Recorded deposit of KSh 100 to 0712 345 678/)).toBeInTheDocument();
});

it("records a deposit without the customer's number or ID", async () => {
  postMpesaTransaction.mockResolvedValue({ internal_reference: "MP-4", customer_phone: "", amount: "200.00", provider_reference: null });
  const posted = vi.fn();
  render(<MpesaDepositForm sessionId={4} onPosted={posted} />);
  expect(screen.getByLabelText("M-Pesa phone number (optional)")).not.toBeRequired();
  expect(screen.getByLabelText("ID or passport number (optional)")).not.toBeRequired();
  fill("Amount (KSh)", "200");
  fireEvent.click(screen.getByRole("button", { name: "Record deposit" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(postMpesaTransaction).toHaveBeenCalledWith(expect.objectContaining({ customer_phone: "", customer_id_number: "", amount: "200" }));
  expect(screen.getByText(/Recorded deposit of KSh 200\. Add its transaction ID/)).toBeInTheDocument();
});

it("fills in a returning customer's ID from their phone number", async () => {
  lookupMpesaCustomer.mockResolvedValue({ found: true, id_number: "34299508", visits: 3 });
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  fill("M-Pesa phone number (optional)", "0712345678");
  await waitFor(() => expect(screen.getByLabelText("ID or passport number (optional)")).toHaveValue("34299508"));
  expect(screen.getByText(/Returning customer/)).toBeInTheDocument();
});

it("fills the code, amount and number from a pasted M-Pesa message, so it can be recorded after the customer leaves", async () => {
  postMpesaTransaction.mockResolvedValue({ internal_reference: "MP-2", customer_phone: "254712345678", amount: "1000.00", provider_reference: "SJK4ABC123" });
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  fireEvent.click(screen.getByText("Paste the M-Pesa message"));
  fill("M-Pesa confirmation message", "SJK4ABC123 Confirmed. Ksh1,000.00 deposited to JANE WANJIRU 254712345678 on 26/9/26. New M-PESA float balance is Ksh25,400.00.");
  expect(screen.getByLabelText("M-Pesa phone number (optional)")).toHaveValue("0712345678");
  expect(screen.getByLabelText("Amount (KSh)")).toHaveValue(1000);
  expect(screen.getByLabelText("Transaction ID (optional)")).toHaveValue("SJK4ABC123");
  fill("ID or passport number (optional)", "12345678");
  fireEvent.click(screen.getByRole("button", { name: "Record deposit" }));
  await waitFor(() => expect(postMpesaTransaction).toHaveBeenCalledWith(expect.objectContaining({ provider_reference: "SJK4ABC123", amount: "1000.00" })));
});

it("a withdrawal asks only for the amount", async () => {
  postMpesaTransaction.mockResolvedValue({ internal_reference: "MP-3", customer_phone: "", amount: "300.00", provider_reference: null });
  const posted = vi.fn();
  render(<MpesaWithdrawalForm sessionId={4} availableCash="500" onPosted={posted} />);
  expect(screen.queryByLabelText("M-Pesa phone number (optional)")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Amount (KSh)")).toHaveAttribute("max", "500");
  fill("Amount (KSh)", "300");
  fireEvent.click(screen.getByRole("button", { name: "Record withdrawal" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(postMpesaTransaction).toHaveBeenCalledWith({ session: 4, transaction_type: "CUSTOMER_WITHDRAWAL", amount: "300", idempotency_key: expect.any(String) });
});

it("shows the server's reason when a deposit is refused, keeping what was typed", async () => {
  postMpesaTransaction.mockRejectedValue(new Error("Enter the customer's M-Pesa number, e.g. 0712 345 678."));
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  fill("M-Pesa phone number (optional)", "123");
  fill("ID or passport number (optional)", "12345678");
  fill("Amount (KSh)", "100");
  fireEvent.click(screen.getByRole("button", { name: "Record deposit" }));
  expect(await screen.findByText(/Enter the customer's M-Pesa number/)).toBeInTheDocument();
  expect(screen.getByLabelText("M-Pesa phone number (optional)")).toHaveValue("123");
});

it("works out the cash and float left after a deposit", () => {
  render(<MpesaDepositForm sessionId={4} availableCash="10000" availableFloat="20000" onPosted={vi.fn()} />);
  fill("Amount (KSh)", "2500");
  expect(screen.getByLabelText("Cash after")).toHaveTextContent("12,500");
  expect(screen.getByLabelText("Float after")).toHaveTextContent("17,500");
  fill("Amount (KSh)", "25000");
  expect(screen.getByRole("alert")).toHaveTextContent("Not enough float");
});

it("works out the cash and float left after a withdrawal", () => {
  render(<MpesaWithdrawalForm sessionId={4} availableCash="10000" availableFloat="20000" onPosted={vi.fn()} />);
  fill("Amount (KSh)", "4000");
  expect(screen.getByLabelText("Cash after")).toHaveTextContent("6,000");
  expect(screen.getByLabelText("Float after")).toHaveTextContent("24,000");
  fill("Amount (KSh)", "12000");
  expect(screen.getByRole("alert")).toHaveTextContent("Not enough physical cash");
});

it("sends the commission balance read after a withdrawal, and clears it for the next one", async () => {
  const posted = vi.fn();
  render(<MpesaWithdrawalForm sessionId={4} onPosted={posted} />);
  fill("Amount (KSh)", "1000");
  fill("Commission balance after (KSh, optional)", "1268.50");
  fireEvent.click(screen.getByRole("button", { name: "Record withdrawal" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(postMpesaTransaction).toHaveBeenCalledWith(expect.objectContaining({ transaction_type: "CUSTOMER_WITHDRAWAL", commission_balance: "1268.50" }));
  expect(screen.getByLabelText("Commission balance after (KSh, optional)")).toHaveValue(null);
});
