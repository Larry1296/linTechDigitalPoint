import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("./api", () => ({ correctMpesaTransaction: vi.fn(async () => ({})) }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
import { correctMpesaTransaction } from "./api";
import { CorrectTransaction } from "./CorrectTransaction";

it("opens with the current figures and sends the corrected ones with a reason", async () => {
  const done = vi.fn();
  render(<CorrectTransaction onDone={done} entry={{ id: 7, transaction_type: "CUSTOMER_DEPOSIT", amount: "700.00", customer_phone: "254712345678",
    customer_id_number: "12345678", provider_reference: "SJK4ABC123" }} />);
  fireEvent.click(screen.getByRole("button", { name: "Correct" }));
  expect(screen.getByLabelText(/Correct amount/)).toHaveValue(700);
  expect(screen.getByLabelText("M-Pesa number (optional)")).toHaveValue("0712345678");
  fireEvent.change(screen.getByLabelText(/Correct amount/), { target: { value: "500" } });
  fireEvent.change(screen.getByLabelText("What was wrong?"), { target: { value: "Typed 700, customer deposited 500" } });
  fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
  await waitFor(() => expect(done).toHaveBeenCalled());
  expect(correctMpesaTransaction).toHaveBeenCalledWith(7, { amount: "500", customer_phone: "0712345678", customer_id_number: "12345678",
    commission_balance: "", provider_reference: "SJK4ABC123", reason: "Typed 700, customer deposited 500" });
});

it("is not offered for a reversal entry", () => {
  const { container } = render(<CorrectTransaction onDone={vi.fn()} entry={{ id: 8, transaction_type: "REVERSAL", amount: "700" }} />);
  expect(container).toBeEmptyDOMElement();
});
