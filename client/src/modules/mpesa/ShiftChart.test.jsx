import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { ShiftChart, shiftSeries } from "./ShiftChart";

const at = (minutes) => new Date(Date.UTC(2026, 9, 10, 5, minutes)).toISOString();
const entry = (id, type, minutes, amount, earned, source = "measured", extra = {}) => ({
  id, transaction_type: type, occurred_at: at(minutes), amount, commission_earned: earned, commission_source: earned == null ? null : source, reversal_of: null, ...extra });
const transactions = [
  entry(1, "CUSTOMER_WITHDRAWAL", 10, "1000.00", "12.00"),
  entry(2, "CUSTOMER_DEPOSIT", 40, "500.00", "8.00", "learned"),
  entry(3, "CUSTOMER_WITHDRAWAL", 50, "700.00", null),
  entry(4, "CUSTOMER_WITHDRAWAL", 55, "900.00", "12.00"),
  entry(5, "REVERSAL", 58, "900.00", null, "measured", { reversal_of: 4 }),
  entry(6, "FLOAT_TOPUP", 59, "5000.00", null),
];

it("runs the shift's totals from opening to closing, leaving out reversed ones and other movements", () => {
  const points = shiftSeries(transactions, at(0), at(120));
  expect(points.map((p) => [p.kind, p.count, p.commission, p.unknown])).toEqual([
    ["open", 0, 0, 0], ["transaction", 1, 12, 0], ["transaction", 2, 20, 0], ["transaction", 3, 20, 1], ["close", 3, 20, 1]]);
  expect(points[points.length - 1].time).toBe(new Date(at(120)).getTime());
});

it("shows the totals, the two charts and the same figures as a table", () => {
  render(<ShiftChart transactions={transactions} openedAt={at(0)} closedAt={at(120)} />);
  expect(screen.getByRole("img", { name: /Transactions so far: 3/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Commission earned so far: KSh 20/ })).toBeInTheDocument();
  expect(screen.getByText(/1 transaction's commission is not worked out yet/)).toBeInTheDocument();
  const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("cell").map((c) => c.textContent));
  expect(rows).toEqual([["Withdrawal", "1,000", "12", "12"], ["Deposit", "500", "≈ 8", "20"], ["Withdrawal", "700", "—", "20"]]);
});

it("reads any moment with the arrow keys", () => {
  render(<ShiftChart transactions={transactions} openedAt={at(0)} closedAt={at(120)} />);
  const plot = screen.getByLabelText(/use the left and right arrow keys/);
  fireEvent.keyDown(plot, { key: "Home" });
  expect(screen.getByRole("status")).toHaveTextContent("Shift opened");
  fireEvent.keyDown(plot, { key: "ArrowRight" });
  expect(screen.getByRole("status")).toHaveTextContent(/Withdrawal.*KSh 1,000 · commission KSh 12.*So far: 1 transaction, KSh 12 commission/);
});
