import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MpesaDepositForm } from "./MpesaDepositForm";
import { MpesaWithdrawalForm } from "./MpesaWithdrawalForm";
import { getCommissionAdvice, lookupMpesaCustomer, postMpesaTransaction } from "./api";
import { confirmAction } from "../../core/ui/alerts";
vi.mock("./api", () => ({ postMpesaTransaction: vi.fn(), lookupMpesaCustomer: vi.fn(), getCommissionAdvice: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  lookupMpesaCustomer.mockResolvedValue({ found: false });
  getCommissionAdvice.mockResolvedValue({ earned: null, ask: true, reason: "new" });
  postMpesaTransaction.mockResolvedValue({ internal_reference: "MP-1", customer_phone: "254712345678", amount: "100.00", provider_reference: null });
});

const fill = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

it("records a deposit straight away, with no confirmation pop-up", async () => {
  const posted = vi.fn();
  render(<MpesaDepositForm sessionId={4} onPosted={posted} />);
  fill("M-Pesa phone number", "0712345678");
  fill("ID or passport number", "12345678");
  fill("Amount (KSh)", "100");
  fireEvent.click(screen.getByRole("button", { name: "Record deposit" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(confirmAction).not.toHaveBeenCalled();
  expect(postMpesaTransaction).toHaveBeenCalledWith({ session: 4, transaction_type: "CUSTOMER_DEPOSIT", amount: "100",
    customer_phone: "0712345678", customer_id_number: "12345678", idempotency_key: expect.any(String) });
  expect(screen.getByLabelText("M-Pesa phone number")).toHaveValue("");
  expect(screen.getByText(/Recorded deposit of KSh 100 to 0712 345 678/)).toBeInTheDocument();
});

it("a deposit needs the customer's number and ID, and no transaction ID", () => {
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  expect(screen.getByLabelText("M-Pesa phone number")).toBeRequired();
  expect(screen.getByLabelText("ID or passport number")).toBeRequired();
  expect(screen.queryByLabelText(/Transaction ID/)).not.toBeInTheDocument();
  expect(screen.queryByText("Paste the M-Pesa message")).not.toBeInTheDocument();
});

it("fills in a returning customer's ID from their phone number", async () => {
  lookupMpesaCustomer.mockResolvedValue({ found: true, id_number: "34299508", visits: 3 });
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  fill("M-Pesa phone number", "0712345678");
  await waitFor(() => expect(screen.getByLabelText("ID or passport number")).toHaveValue("34299508"));
  expect(screen.getByText(/Returning customer/)).toBeInTheDocument();
});

it("a withdrawal asks only for the amount", async () => {
  postMpesaTransaction.mockResolvedValue({ internal_reference: "MP-3", customer_phone: "", amount: "300.00", provider_reference: null });
  const posted = vi.fn();
  render(<MpesaWithdrawalForm sessionId={4} availableCash="500" onPosted={posted} />);
  expect(screen.queryByLabelText("M-Pesa phone number")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Amount (KSh)")).toHaveAttribute("max", "500");
  fill("Amount (KSh)", "300");
  fireEvent.click(screen.getByRole("button", { name: "Record withdrawal" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(postMpesaTransaction).toHaveBeenCalledWith({ session: 4, transaction_type: "CUSTOMER_WITHDRAWAL", amount: "300", idempotency_key: expect.any(String) });
});

it("shows the server's reason when a deposit is refused, keeping what was typed", async () => {
  postMpesaTransaction.mockRejectedValue(new Error("Enter the customer's M-Pesa number, e.g. 0712 345 678."));
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  fill("M-Pesa phone number", "123");
  fill("ID or passport number", "12345678");
  fill("Amount (KSh)", "100");
  fireEvent.click(screen.getByRole("button", { name: "Record deposit" }));
  expect(await screen.findByText(/Enter the customer's M-Pesa number/)).toBeInTheDocument();
  expect(screen.getByLabelText("M-Pesa phone number")).toHaveValue("123");
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
  fireEvent.change(await screen.findByLabelText("Commission balance after (KSh, optional)"), { target: { value: "1268.50" } });
  fireEvent.click(screen.getByRole("button", { name: "Record withdrawal" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  expect(postMpesaTransaction).toHaveBeenCalledWith(expect.objectContaining({ transaction_type: "CUSTOMER_WITHDRAWAL", commission_balance: "1268.50" }));
  await waitFor(() => expect(screen.queryByLabelText("Commission balance after (KSh, optional)")).not.toBeInTheDocument()); // the form starts afresh
});

it("drops the commission balance box once the app has learned the amount", async () => {
  getCommissionAdvice.mockResolvedValue({ earned: "12.00", ask: false, reason: null });
  render(<MpesaWithdrawalForm sessionId={4} onPosted={vi.fn()} />);
  fill("Amount (KSh)", "1000");
  expect(await screen.findByText(/worked out automatically/)).toBeInTheDocument();
  expect(getCommissionAdvice).toHaveBeenCalledWith(4, "CUSTOMER_WITHDRAWAL", "1000");
  expect(screen.queryByLabelText("Commission balance after (KSh, optional)")).not.toBeInTheDocument();
});

it("asks for one reading at the yearly check of a learned rate", async () => {
  getCommissionAdvice.mockResolvedValue({ earned: "12.00", ask: true, reason: "yearly", matched: 2, needed: 5 });
  render(<MpesaWithdrawalForm sessionId={4} onPosted={vi.fn()} />);
  fill("Amount (KSh)", "1000");
  expect(await screen.findByText(/Yearly check of Safaricom's rates: the app works this out as KSh 12.*2 of 5 in a row have matched/)).toBeInTheDocument();
  expect(screen.getByLabelText("Commission balance after (KSh, optional)")).toBeInTheDocument();
});

it("asks now and then to check the learned rates are on track", async () => {
  getCommissionAdvice.mockResolvedValue({ earned: "12.00", ask: true, reason: "spot", matched: null, needed: 5 });
  render(<MpesaWithdrawalForm sessionId={4} onPosted={vi.fn()} />);
  fill("Amount (KSh)", "1000");
  expect(await screen.findByText(/Quick check that the app is on track: it works this out as KSh 12/)).toBeInTheDocument();
});

it("asks after each transaction once the rates may have changed", async () => {
  getCommissionAdvice.mockResolvedValue({ earned: "12.00", ask: true, reason: "changed", matched: 0, needed: 5 });
  render(<MpesaWithdrawalForm sessionId={4} onPosted={vi.fn()} />);
  fill("Amount (KSh)", "1000");
  expect(await screen.findByText(/Safaricom's rates may have changed: two checks in a row did not match/)).toBeInTheDocument();
});

it("asks for the commission balance while the app is still learning the amount", async () => {
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  expect(screen.queryByLabelText("Commission balance after (KSh, optional)")).not.toBeInTheDocument();
  fill("Amount (KSh)", "700");
  expect(await screen.findByText(/still learning the commission on this amount/)).toBeInTheDocument();
  expect(screen.getByLabelText("Commission balance after (KSh, optional)")).toBeInTheDocument();
});
