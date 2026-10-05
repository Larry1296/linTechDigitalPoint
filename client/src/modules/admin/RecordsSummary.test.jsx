import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { RecordsSummary } from "./RecordsSummary";

const money = (value) => `KSh ${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
const records = {
  since: "2026-09-30",
  catalogue: { categories: 11, brands: 12, products: 17, items: 17, items_active: 17, services: 6 },
  stock: { units_received: "824", units_on_shelves: "821", items_in_stock: 16, deliveries: 17, without_buying_price: 0,
    below_cost: [{ id: 16, name: "A4 envelopes", quantity: "50", unit_cost: "140.00", selling_price: "10.00" }] },
  sales: { completed: 7, cancelled: 4, by_channel: { POS: 3, CYBER: 4 }, units_sold: "12", revenue: "2780", cogs: "1550", gross_profit: "1230",
    returns: 0, refunded: "0", paid: "1980", paid_by_method: { CASH: "1980" }, refunded_payments: "220", reversed_payments: "200", failed_payments: "250", waiting_payments: "0" },
  services: { completed: 4, completed_value: "330", in_progress: 0, in_progress_value: "0", cancelled: 4 },
  mpesa: { outlets: 1, shifts_open: 0, shifts_closed: 1, deposits: 9, deposits_value: "2750", withdrawals: 3, withdrawals_value: "4900", float_topups: "0", commission: "0" },
  money: { expenses: 0, expenses_value: "0", loans: 0, loans_value: "0", loans_outstanding: "0", investments: 1, investments_value: "0" },
  profit: { revenue: "2780", cogs: "1550", expenses: "0", stock_corrections: "0", profit: "1230" },
};

it("shows every part of the business with exact figures and flags items priced below cost", () => {
  render(<RecordsSummary records={records} money={money} />);
  expect(screen.getByText(/= KSh 1,230.00 profit/)).toBeInTheDocument();
  const row = (label) => screen.getByText(label).closest("div");
  expect(row("Sales made")).toHaveTextContent("7 (3 at the counter, 4 services)");
  expect(row("Items on the shelves now")).toHaveTextContent("821");
  expect(row("Customer deposits")).toHaveTextContent("9 deposits · KSh 2,750.00");
  expect(row("Paid by cash")).toHaveTextContent("KSh 1,980.00");
  expect(row("Failed (no money came in)")).toHaveTextContent("KSh 250.00");
  expect(row("Done")).toHaveTextContent("4 · KSh 330.00");
  expect(screen.getByRole("note")).toHaveTextContent("A4 envelopes: 50 in stock, cost KSh 140.00 each, selling price KSh 10.00");
});

it("leaves out parts the viewer may not see", () => {
  render(<RecordsSummary records={{ ...records, money: null, profit: null, mpesa: null }} money={money} />);
  expect(screen.queryByRole("heading", { name: "M-Pesa agency" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Money spent, lent and invested" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Sales" })).toBeInTheDocument();
});
