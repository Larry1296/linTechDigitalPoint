import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { NetWorthPanel } from "./NetWorthPanel";

const money = (value) => `KES ${Number(value).toLocaleString()}`;
const worth = { as_of: "2026-10-02T09:00:00Z", owns: "35500", owes: "200", net_worth: "35300", left_out: [],
  groups: [
    { key: "money", label: "Shop money (drawer, till, bank)", side: "OWNS", amount: "7100", items: [
      { key: "shop-mpesa", label: "Lipa na M-Pesa till", amount: "7500", method: "MPESA", counted: "7400", counted_at: "2026-10-01T18:00:00Z", difference: "-100" },
      { key: "shop-cash", label: "Cash in the drawer", amount: "-400", method: "CASH", counted: null, counted_at: null, difference: null }] },
    { key: "agency", label: "M-Pesa agency cash and float", side: "OWNS", amount: "25000", items: [
      { key: "agency-1", label: "Agent till", amount: "25000", cash: "6000", float: "19000", state: "OPEN", since: "2026-10-02T05:00:00Z", opening_cash: "5000", opening_float: "20000" }] },
    { key: "investments", label: "Investments", side: "OWNS", amount: "3000", items: [{ key: "investment-1", label: "CIC MMF", amount: "3000", estimated_interest: "12.40" }] },
    { key: "stock", label: "Stock on the shelves (at cost)", side: "OWNS", amount: "400", items: [] },
    { key: "expenses", label: "Running costs not yet paid", side: "OWES", amount: "200", items: [] }],
  history: [{ date: "2026-10-01", owns: "34000", owes: "0", net_worth: "34000" }, { date: "2026-10-02", owns: "35500", owes: "200", net_worth: "35300" }] };

it("shows the net worth, what makes it up and the live agency shift money", () => {
  render(<NetWorthPanel worth={worth} money={money} />);
  const panel = screen.getByRole("region", { name: "What the business is worth" });
  expect(panel.querySelector(".netWorthHero strong")).toHaveTextContent("KES 35,300");
  expect(within(panel).getByText("Owns KES 35,500 · owes KES 200")).toBeInTheDocument();
  const bars = within(panel).getByRole("list", { name: /owns and owes/ });
  const labels = within(bars).getAllByRole("listitem").map((li) => li.textContent);
  expect(labels[0]).toContain("M-Pesa agency cash and float");  // largest first
  expect(labels.at(-1)).toBe("Owes · Running costs not yet paid− KES 200");  // what is owed comes last, marked
  const agent = within(panel).getByRole("row", { name: /Agent till/ });
  expect(agent).toHaveTextContent("opened with cash KES 5,000 and float KES 20,000 · now cash KES 6,000, float KES 19,000");
  expect(within(panel).getByRole("row", { name: /Lipa na M-Pesa till/ })).toHaveTextContent("less than expected by KES 100");
  expect(within(panel).getByRole("row", { name: /Cash in the drawer/ })).toHaveTextContent("below zero");
  expect(within(panel).getByRole("row", { name: /CIC MMF/ })).toHaveTextContent("not counted until confirmed");
  expect(within(within(panel).getByRole("row", { name: /Lipa na M-Pesa till/ })).getByRole("link", { name: "Count or correct" })).toHaveAttribute("href", "/admin/money-check");
});

it("explains each day on the trend and says what it could not include", () => {
  const { container } = render(<NetWorthPanel worth={{ ...worth, left_out: ["Stock on the shelves (at cost)"] }} money={money} />);
  expect(screen.getByText(/Not included because your account cannot see it: Stock/)).toBeInTheDocument();
  const chart = container.querySelector(".netWorthTrend svg");
  chart.getBoundingClientRect = () => ({ left: 0, width: 600, top: 0, height: 170 });
  fireEvent.mouseMove(chart, { clientX: 590 });
  expect(container.querySelector(".netWorthTip")).toHaveTextContent(/KES 35,300 \(owns KES 35,500, owes KES 200\)/);
});

it("waits for a second day before drawing a trend", () => {
  render(<NetWorthPanel worth={{ ...worth, history: worth.history.slice(0, 1) }} money={money} />);
  expect(screen.getByText(/trend appears from tomorrow/)).toBeInTheDocument();
});
