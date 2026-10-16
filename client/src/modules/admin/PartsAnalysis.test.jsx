import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { PartsAnalysis, partsStory } from "./PartsAnalysis";

const money = (value) => `KSh ${Number(value).toLocaleString()}`;
const unit = (key, name, revenue, cogs, expenses, profit) => ({ key, name, revenue, cogs, expenses, stock_corrections: "0", profit });
const data = {
  has_parts: true,
  period_summary: { start: "2026-10-01", end: "2026-10-14" },
  unit_period: [unit("SHOP", "Shop", "12000", "7000", "1000", "4000"), unit("CYBER", "Cyber", "3000", "0", "500", "2500"),
    unit("MPESA", "M-Pesa", "1020", "0", "1500", "-480")],
  unit_trend: [{ month: "2026-09", SHOP_sales: "9000", SHOP_costs: "800", SHOP_profit: "3000", CYBER_sales: "2000", CYBER_costs: "500", CYBER_profit: "1500",
    MPESA_sales: "900", MPESA_costs: "500", MPESA_profit: "400", TOTAL_sales: "11900", TOTAL_costs: "1800", TOTAL_profit: "4900" },
  { month: "2026-10", SHOP_sales: "12000", SHOP_costs: "1000", SHOP_profit: "4000", CYBER_sales: "3000", CYBER_costs: "500", CYBER_profit: "2500",
    MPESA_sales: "1020", MPESA_costs: "1500", MPESA_profit: "-480", TOTAL_sales: "16020", TOTAL_costs: "3000", TOTAL_profit: "6020" }],
  unit_days: [],
};

it("says in words which part carries the business, which made a loss and how each moved since last month", () => {
  const parts = data.unit_period.map((u) => ({ key: u.key, income: Number(u.revenue), profit: Number(u.profit) }));
  const story = partsStory(parts, data.unit_trend, money);
  expect(story[0]).toBe("Shop made the most profit: KSh 4,000, 62% of what the profitable parts earned.");
  expect(story).toContain("M-Pesa made a loss of KSh 480: its costs were more than it brought in.");
  expect(story).toContain("Cyber's profit this month is KSh 1,000 more than last month (KSh 1,500 → KSh 2,500).");
});

it("compares the parts side by side and leaves the agency's cash and float out", () => {
  render(<PartsAnalysis data={data} money={money} />);
  expect(screen.getByRole("heading", { name: "How each part of the business is doing" })).toBeInTheDocument();
  expect(screen.getByText(/its cash and float are the agency's working money/)).toBeInTheDocument();
  expect(screen.getByText("Income, costs and profit of each part")).toBeInTheDocument();
  expect(screen.getByText("Share of the profit")).toBeInTheDocument();
  expect(screen.getByText("Profit each month, part by part")).toBeInTheDocument();
});

it("is not shown for a business with one part", () => {
  const { container } = render(<PartsAnalysis data={{ ...data, unit_period: data.unit_period.slice(0, 1) }} money={money} />);
  expect(container).toBeEmptyDOMElement();
});

it("shows what each part contributed, adding up to the whole business, with the owner's own names", () => {
  const named = { ...data, unit_period: data.unit_period.map((u) => (u.key === "CYBER" ? { ...u, name: "Cyber café" } : u)) };
  render(<PartsAnalysis data={named} money={money} />);
  const table = screen.getByRole("table", { name: "What each part contributed to the whole business" });
  const row = (name) => within(table).getByRole("row", { name: new RegExp(`^${name}`) });
  expect(row("Cyber café")).toHaveTextContent("KSh 3,000" + "19%" + "KSh 500" + "KSh 2,500");
  expect(row("M-Pesa")).toHaveTextContent("−KSh 480");
  // 4,000 + 2,500 − 480: the parts add up to the whole business.
  expect(row("Whole business")).toHaveTextContent("KSh 16,020" + "100%" + "KSh 10,000" + "KSh 6,020");
  expect(screen.getByText("Running costs each month, part by part")).toBeInTheDocument();
  expect(screen.getAllByText("Whole business").length).toBeGreaterThan(1);  // the table's total and the charts' dashed line
});

it("is not shown when the owner runs it as one business", () => {
  const { container } = render(<PartsAnalysis data={{ ...data, has_parts: false }} money={money} />);
  expect(container).toBeEmptyDOMElement();
});
