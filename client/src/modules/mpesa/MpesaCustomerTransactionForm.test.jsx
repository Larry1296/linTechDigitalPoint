import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MpesaDepositForm } from "./MpesaDepositForm";
import { MpesaWithdrawalForm } from "./MpesaWithdrawalForm";
import { postMpesaTransaction } from "./api";
import { confirmAction } from "../../core/ui/alerts";
vi.mock("./api", () => ({ postMpesaTransaction: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  confirmAction.mockResolvedValue(true);
  postMpesaTransaction.mockResolvedValue({ internal_reference: "MP-1" });
});
it.each([
  [MpesaDepositForm, "CUSTOMER_DEPOSIT", "deposit"],
  [MpesaWithdrawalForm, "CUSTOMER_WITHDRAWAL", "withdrawal"],
])(
  "posts the correct transaction through the shared form (%s)",
  async (Component, type, name) => {
    const posted = vi.fn();
    render(<Component sessionId={4} availableCash="500" onPosted={posted} />);
    const amount = screen.getByLabelText("Amount (KES)");
    fireEvent.change(amount, { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("M-Pesa agency reference"), {
      target: { value: "REF" },
    });
    if (name === "deposit")
      fireEvent.change(screen.getByLabelText("Notes"), {
        target: { value: "Sample" },
      });
    else expect(amount).toHaveAttribute("max", "500");
    fireEvent.click(screen.getByRole("button", { name: `Record ${name}` }));
    await waitFor(() => expect(posted).toHaveBeenCalledOnce());
    expect(postMpesaTransaction).toHaveBeenCalledWith(
      expect.objectContaining({
        session: 4,
        transaction_type: type,
        amount: "100",
        provider_reference: "REF",
        idempotency_key: expect.any(String),
      }),
    );
    const payload = postMpesaTransaction.mock.calls[0][0];
    if (name === "deposit") expect(payload.notes).toBe("Sample");
    else expect(payload).not.toHaveProperty("notes");
    expect(amount.value).toBe("");
    expect(screen.getByText("Recorded MP-1")).toBeInTheDocument();
  },
);
it("does not post or clear the form when confirmation is cancelled", async () => {
  confirmAction.mockResolvedValue(false);
  render(<MpesaDepositForm sessionId={4} onPosted={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Amount (KES)"), {
    target: { value: "100" },
  });
  fireEvent.change(screen.getByLabelText("M-Pesa agency reference"), {
    target: { value: "REF" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Record deposit" }));
  await waitFor(() => expect(confirmAction).toHaveBeenCalledOnce());
  expect(postMpesaTransaction).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Amount (KES)")).toHaveValue(100);
});
