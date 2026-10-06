import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { OwnerSummary } from "./OwnerSummary";

const money = (value) => `KSh ${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
const summary = {
  since: "2026-09-30",
  today: { products: "0", services: "20", sales: "20", cost: "0", expenses: "50", stock_corrections: "0", profit: "-30" },
  all_time: { products: "2460", services: "350", sales: "2810", cost: "1552.80", expenses: "50", stock_corrections: "0", profit: "1207.20" },
  money: { expected: "11960", places: [{ method: "CASH", label: "Cash in the drawer", expected: "11960" }],
    parts: [{ key: "starting", label: "Starting money", amount: "10000" }, { key: "received", label: "Received from customers (less refunds)", amount: "2010" },
      { key: "expenses", label: "Spent on running costs", amount: "-50" }, { key: "suppliers", label: "Paid to suppliers", amount: "0" }] },
  customers_owe: "800",
};

it("shows sales, true cost, profit or loss and the money the owner should hold", () => {
  render(<OwnerSummary summary={summary} money={money} />);
  const row = (label) => screen.getByRole("row", { name: new RegExp(label) });
  expect(row("Services")).toHaveTextContent("KSh 20.00KSh 350.00");
  expect(row("What the sold items cost you")).toHaveTextContent("KSh 1,552.80");
  expect(row("Profit or loss")).toHaveTextContent("KSh 30.00 loss");
  expect(row("Profit or loss")).toHaveTextContent("KSh 1,207.20 profit");
  expect(screen.getByText("Spent on running costs").closest("div")).toHaveTextContent("− KSh 50.00");
  expect(screen.queryByText("Paid to suppliers")).toBeNull();
  expect(screen.getByText("You should have").closest("div")).toHaveTextContent("KSh 11,960.00");
  expect(screen.getByText(/Customers still owe you/)).toHaveTextContent("KSh 800.00");
});

it("leaves out what the viewer may not see", () => {
  const hidden = { cost: null, expenses: null, stock_corrections: null, profit: null };
  render(<OwnerSummary summary={{ ...summary, today: { ...summary.today, ...hidden }, all_time: { ...summary.all_time, ...hidden }, money: null }} money={money} />);
  expect(screen.queryByRole("row", { name: /Profit or loss/ })).toBeNull();
  expect(screen.queryByText("Money you should be holding now")).toBeNull();
  expect(screen.getByRole("row", { name: /Total sales/ })).toHaveTextContent("KSh 2,810.00");
});
