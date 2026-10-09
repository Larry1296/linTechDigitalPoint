import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { BusinessAnalysis, byWeekday, withWeekAverage } from "./BusinessAnalysis";

const money = (value) => `KES ${Number(value).toFixed(2)}`;
const days = Array.from({ length: 14 }, (_, i) => ({ date: `2026-09-${String(i + 1).padStart(2, "0")}`, revenue: (i + 1) * 10, expenses: 5, profit: (i + 1) * 10 - 15 }));

it("averages the last seven days once there are seven of them", () => {
  const rows = withWeekAverage(days);
  expect(rows[5].average).toBeNull();
  expect(rows[6].average).toBe(40);  // 10..70
  expect(rows[13].average).toBe(110);  // 80..140
});

it("averages sales on each day of the week that came up", () => {
  // 1 Sep 2026 is a Tuesday: two Tuesdays (1st, 8th) average (10 + 80) / 2.
  const week = byWeekday(days);
  expect(week[0]).toEqual({ day: "Monday", average: (70 + 140) / 2 });
  expect(week[1]).toEqual({ day: "Tuesday", average: 45 });
});

it("lays out the analysis for the picked dates, leaving out what the user cannot see", () => {
  const data = {
    period_summary: { start: "2026-09-01", end: "2026-09-14" },
    performance: { granularity: "day", points: days },
    unit_period: [{ key: "SHOP", name: "Products / sales", revenue: 900, cogs: 500, expenses: 100, stock_corrections: 0, profit: 300 },
      { key: "MPESA", name: "M-Pesa agency", revenue: 150, cogs: 0, expenses: 200, stock_corrections: 0, profit: -50 }],
    top_items: [{ id: 1, name: "Cable — 1m", quantity: 3, sales: 600 }],
    expense_breakdown: [{ category: "Rent", business_unit: "SHOP", amount: 50 }, { category: "Rent", business_unit: "MPESA", amount: 20 }],
    financial_trend: [{ month: "2026-08", sales: 100, expenses: 10, profit: 20 }, { month: "2026-09", sales: 200, expenses: 20, profit: -10 }],
  };
  render(<BusinessAnalysis data={data} money={money} />);
  for (const title of ["Sales each day", "Sales, running costs and profit", "Where the sales came from", "Best sellers", "Where the running costs went",
    "Busiest days of the week", "The last twelve months", "Profit kept from each 100 of sales", "Profit or loss by part of the business"]) {
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  }
  expect(screen.getByText(/On average, Monday brings the most sales/)).toBeInTheDocument();
  const costs = screen.getByRole("heading", { name: "Where the running costs went" }).closest("figure");
  expect(within(costs).getByRole("listitem")).toHaveTextContent("RentKES 70.00 100%");  // rent from both parts of the business together
});

it("shows only sales when profit is not the user's to see", () => {
  const data = {
    period_summary: { start: "2026-09-01", end: "2026-09-14" },
    performance: { granularity: "day", points: days.map((d) => ({ ...d, expenses: null, profit: null })) },
    financial_trend: [{ month: "2026-09", sales: 200, expenses: null, profit: null }],
  };
  render(<BusinessAnalysis data={data} money={money} />);
  expect(screen.getByRole("heading", { name: "Sales each day" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Sales, running costs and profit" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Profit kept from each 100 of sales" })).toBeNull();
});
