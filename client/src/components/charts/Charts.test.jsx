import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { BarList, ColumnChart, LineChart, compact, niceScale } from "./Charts";

const money = (value) => `KSh ${Number(value).toLocaleString()}`;
const label = { header: "Day", short: (p) => p.day, full: (p) => `Day ${p.day}` };
const points = [{ day: "1", sales: 100, profit: -20 }, { day: "2", sales: 250, profit: 40 }, { day: "3", sales: 180, profit: null }];

it("keeps round axis steps that cover losses as well as gains", () => {
  expect(niceScale([100, 250, -20])).toEqual({ ticks: [0, 100, 200, 300], min: -24, max: 300 });  // a small loss: just below it
  expect(niceScale([100, 250, -60])).toEqual({ ticks: [-100, 0, 100, 200, 300], min: -100, max: 300 });
  expect(niceScale([0, 0])).toEqual({ ticks: [0, 1], min: 0, max: 1 });
  expect([compact(1250), compact(12500), compact(4200000)]).toEqual(["1,250", "12.5K", "4.2M"]);
});

it("draws a line per series, with a legend, a keyboard tooltip and the numbers as a table", () => {
  render(<LineChart title="Sales" points={points} label={label} format={money}
    series={[{ key: "sales", label: "Sales" }, { key: "profit", label: "Profit" }, { key: "hidden", label: "Never shown" }]} />);
  expect(screen.getByRole("img", { name: /Sales ends at KSh 180/ })).toBeInTheDocument();
  expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Sales", "Profit"]);  // a series with no figures is left out
  const plot = screen.getByLabelText(/arrow keys/);
  fireEvent.keyDown(plot, { key: "Home" });
  expect(screen.getByRole("status")).toHaveTextContent("Day 1SalesKSh 100ProfitKSh -20");
  fireEvent.keyDown(plot, { key: "End" });
  expect(screen.getByRole("status")).toHaveTextContent("Day 3SalesKSh 180Profit—");
  const rows = within(screen.getByRole("table")).getAllByRole("row").map((row) => row.textContent);
  expect(rows).toEqual(["DaySalesProfit", "Day 1KSh 100KSh -20", "Day 2KSh 250KSh 40", "Day 3KSh 180—"]);
});

it("draws columns up for gains and down for losses", () => {
  const { container } = render(<ColumnChart title="Months" points={points} label={label} format={money}
    series={[{ key: "sales", label: "Sales" }, { key: "profit", label: "Profit" }]} />);
  expect(container.querySelectorAll("path")).toHaveLength(5);  // three sales columns, two profit columns (one month has none)
  fireEvent.keyDown(screen.getByLabelText(/arrow keys/), { key: "ArrowLeft" });
  expect(screen.getByRole("status")).toHaveTextContent("Day 2SalesKSh 250ProfitKSh 40");
});

it("ranks bars biggest first, folds the rest into others and shows each share", () => {
  render(<BarList title="Best sellers" rows={[{ label: "Tea", value: 50 }, { label: "Bread", value: 300 }, { label: "Milk", value: 150 }, { label: "None", value: 0 }]}
    format={money} limit={2} empty="Nothing" />);
  expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["BreadKSh 300 60%", "MilkKSh 150 30%", "1 othersKSh 50 10%"]);
});

it("says so when there is nothing to rank", () => {
  render(<BarList title="Best sellers" rows={[]} format={money} empty="No products sold in these dates." />);
  expect(screen.getByText("No products sold in these dates.")).toBeInTheDocument();
});
