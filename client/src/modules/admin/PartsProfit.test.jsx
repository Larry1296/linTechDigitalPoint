import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { PartsProfit } from "./PartsProfit";

const money = (value) => `KSh ${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
const units = [
  { key: "SHOP", name: "Shop", all_time: { revenue: "1500", cogs: "200", expenses: "100", profit: "1200" } },
  { key: "CYBER", name: "Cyber", all_time: { revenue: "300", cogs: "0", expenses: "350", profit: "-50" } },
  { key: "MPESA", name: "M-Pesa", all_time: { revenue: "900", cogs: "0", expenses: "0", profit: "900" } },
  { key: "OTHER", name: "Hidden", restricted: true, all_time: { revenue: "5", profit: "5" } },
];

it("adds up only each part's profit, with a link to each part's own page", () => {
  render(<PartsProfit units={units} total="2050" money={money} />);
  expect(screen.getByRole("link", { name: "Shop" })).toHaveAttribute("href", "/admin/sales-history");
  expect(screen.getByRole("row", { name: /Cyber/ })).toHaveTextContent("KSh 50.00 loss");
  expect(screen.getByRole("row", { name: /M-Pesa/ })).toHaveTextContent("Commission paid");
  expect(screen.queryByText("Hidden")).toBeNull();
  expect(screen.getByRole("row", { name: /every part together/ })).toHaveTextContent("KSh 2,050.00 profit");
});

it("shows nothing to someone who may not see profit", () => {
  const { container } = render(<PartsProfit units={units.map(unit => ({ ...unit, all_time: { ...unit.all_time, profit: null } }))} total={null} money={money} />);
  expect(container).toBeEmptyDOMElement();
});
