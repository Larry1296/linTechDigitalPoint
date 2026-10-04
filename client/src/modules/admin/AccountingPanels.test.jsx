import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AccountingPanels, AccountingChart, PeriodComparison } from "./AccountingPanels";
afterEach(cleanup);
const money = value => value == null ? "Restricted" : `KES ${Number(value).toFixed(2)}`;
const data = {
  organization: { timezone: "Africa/Nairobi" },
  period_summary: { start: "2026-09-01", end: "2026-09-21", revenue: 50, cogs: 20, expenses: 0, purchases: 200, profit: 30, profit_margin: 60 },
  comparison: { start: "2026-08-01", end: "2026-08-21", metrics: Object.fromEntries(["revenue", "expenses", "purchases", "profit"].map(key => [key, { previous: 0, change: 0, percent: null }])) },
  performance: { granularity: "day", points: [{ date: "2026-09-21", revenue: 50, expenses: 0, profit: 30 }] },
  receivables: { as_of: "2026-09-21", count: 1, outstanding: 150, rows: [{ reference: "SALE-1", customer: "Customer", amount: 150 }] },
  payables: { as_of: "2026-09-21", count: 1, outstanding: 140, rows: [{ reference: "RCV-1", supplier: "Acme Supplier", amount: 140 }] },
  collections: { period_billed: 200, collected_on_period_sales: 50, period_outstanding: 150, rate: 25 },
  inventory: { low_stock: 2 }, top_items: [{ id: 1, name: "Cable", sku: "CAB", quantity: 2, sales: 200 }], account_balances: [], recent_entries: [],
};
it("renders debt, collection and top item panels from the snapshot", () => {
  render(<AccountingPanels data={data} money={money} />);
  expect(screen.getByRole("heading", { name: "Customers owe you" })).toBeInTheDocument();
  expect(screen.getByText("Acme Supplier")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Share of sales paid" })).toHaveAttribute("value", "25");
  expect(screen.getByRole("rowheader", { name: "Cable" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "What the business is worth" })).toBeNull();  // only shown with the net worth figures
});
it("changes chart style while keeping restricted profit out of charts and tables", () => {
  render(<AccountingChart title="Performance" points={[{ date: "2026-09-21", revenue: 50, profit: null }]} fields={["revenue", "profit"]} money={money} />);
  expect(document.querySelectorAll("polyline")).toHaveLength(1);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "bar" } });
  expect(document.querySelectorAll("polyline")).toHaveLength(0);
  expect(document.querySelectorAll("rect")).toHaveLength(1);
  expect(screen.queryByText("Profit / loss")).not.toBeInTheDocument();
});
it("does not invent a percentage when the prior period has no revenue", () => {
  render(<PeriodComparison data={data} money={money} />);
  expect(screen.getByText(/2026-08-01 to 2026-08-21/)).toBeInTheDocument();
  expect(screen.queryByText(/%\)/)).not.toBeInTheDocument();  // no percentage when there is nothing to compare with
});
