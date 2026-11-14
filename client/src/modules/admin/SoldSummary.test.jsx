import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { SoldSummary } from "./SoldSummary";

const money = (value) => `KES ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const sold = {
  total: "1570.00",
  groups: [
    { key: "GOODS", name: "Goods", amount: "600.00", lines: [{ code: "4000", name: "Products", amount: "600.00", sales: 1, quantity: "2.000" }] },
    { key: "SERVICES", name: "Services", amount: "20.00", lines: [{ code: "4020", name: "Services", amount: "20.00", sales: 1, quantity: "2.000" }] },
    { key: "COMMISSION", name: "Commission", amount: "700.00", lines: [{ code: "4010", name: "M-Pesa agency", amount: "700.00", months_paid: 1, coming: "180.00", coming_months: ["November 2026"] }] },
    { key: "INTEREST", name: "Interest", amount: "250.00", lines: [{ code: "4910", name: "Interest earned", amount: "250.00" }] },
  ],
};

test("shows each kind of income with its share, what is behind it, and the total they add up to", () => {
  render(<SoldSummary sold={sold} since="2026-09-01" owedSales="300" money={money} />);
  const card = screen.getByRole("region", { name: "Everything sold and earned" });
  expect(within(card).getByText(/^Since you started · .*2026$/)).toBeInTheDocument();
  expect(within(card).getAllByText("KES 1,570.00").length).toBeGreaterThan(0);
  const goods = within(card).getByRole("article", { name: "Goods" });
  expect(within(goods).getByText("38%")).toBeInTheDocument();
  expect(within(goods).getByText("1 sale · 2 items sold")).toBeInTheDocument();
  expect(within(goods).getByText("Products sold")).toBeInTheDocument();
  expect(within(goods).getByRole("link", { name: /See sales/ })).toHaveAttribute("href", "/admin/sales-history");
  const commission = within(card).getByRole("article", { name: "Commission" });
  expect(within(commission).getByText("Paid to you by Safaricom")).toBeInTheDocument();
  expect(within(commission).getByText(/Safaricom has paid 1 month · KES 180.00 more worked out for November 2026, counted once it is paid/)).toBeInTheDocument();
  expect(within(card).getByRole("img", { name: "Share of the total: Goods 38%, Services 1%, Commission 45%, Interest 16%" })).toBeInTheDocument();
  expect(within(card).getByText("Total sold and earned")).toBeInTheDocument();
  expect(within(card).getByText(/It is not the money you have now/)).toBeInTheDocument();
  expect(within(card).getByText("Goods + Services + Commission + Interest = total sold and earned")).toBeInTheDocument();
  expect(within(card).getByText(/KES 600.00 \+ KES 20.00 \+ KES 700.00 \+ KES 250.00 =/)).toBeInTheDocument();
  expect(within(card).getByText(/Includes KES 300.00 sold on credit/)).toBeInTheDocument();
});

test("shows nothing when the viewer may see no part of the business", () => {
  const { container } = render(<SoldSummary sold={null} money={money} />);
  expect(container).toBeEmptyDOMElement();
});

test("explains, step by step, why the business's money is not the total sold and earned", () => {
  // LinTech's own figures on 14 Nov 2026: 25,234.08 of the business's money is in the CIC fund.
  const bridge = { money_now: "29529.08", in_places: "4295.00", in_investments: "25234.08", interest: "911.08", lines: [
    { key: "not_received", amount: "-180.00" }, { key: "starting", amount: "800.00" }, { key: "own_for_suppliers", amount: "6909.60" },
    { key: "found", amount: "4900.00" }, { key: "agency", amount: "1800.00" }, { key: "suppliers", amount: "-6909.60" }] };
  render(<SoldSummary sold={{ ...sold, total: "22209.08" }} bridge={bridge} money={money} />);
  const fold = screen.getByText("Why the business's money now (KES 29,529.08, KES 25,234.08 of it in investments) is not this total").closest("details");
  const steps = [...fold.querySelectorAll(".soldSteps > div")].map((row) => row.textContent);
  expect(steps).toEqual(["Total sold and earnedKES 22,209.08", "Sold but not paid yet (customers still owe it)− KES 180.00",
    "Money the business started with+ KES 800.00", "Your own money put in to pay suppliers+ KES 6,909.60",
    "Business money that was already in the investment (the app had not seen it)+ KES 4,900.00", "Moved in from the M-Pesa agency's cash+ KES 1,800.00",
    "Paid to suppliers for stock− KES 6,909.60", "The business's money nowKES 29,529.08"]);
  expect(within(fold).getByRole("link", { name: "KES 4,295.00 in the drawer, till and bank" })).toHaveAttribute("href", "/admin/money-check");
  expect(within(fold).getByRole("link", { name: "KES 25,234.08 kept in investments" })).toHaveAttribute("href", "/admin/investments");
});

test("says all of the business's money is in investments when the drawer, till and bank hold none", () => {
  // LinTech after the drawer's 4,295 was recorded as already in CIC: the money now is exactly the investment.
  const bridge = { money_now: "25234.08", in_places: "0.00", in_investments: "25234.08", interest: "911.08", lines: [
    { key: "not_received", amount: "-180.00" }, { key: "starting", amount: "800.00" }, { key: "own_for_suppliers", amount: "6909.60" },
    { key: "found", amount: "605.00" }, { key: "agency", amount: "1800.00" }, { key: "suppliers", amount: "-6909.60" }] };
  render(<SoldSummary sold={{ ...sold, total: "22209.08" }} bridge={bridge} money={money} />);
  const fold = screen.getByText("Why the business's money now (KES 25,234.08, all of it in investments) is not this total").closest("details");
  expect(within(fold).getByText(/Business money that was already in the investment/).nextSibling).toHaveTextContent("+ KES 605.00");
  expect(within(fold).getByRole("link", { name: "KES 25,234.08, is kept in investments" })).toHaveAttribute("href", "/admin/investments");
  expect(within(fold).getByText(/Nothing is left in the drawer, till or bank/)).toBeInTheDocument();
  // The dashboard shows the money the business holds at a glance, next to the total sold and earned.
  const now = screen.getByRole("link", { name: /The business's money now/ });
  expect(now).toHaveTextContent("The business's money nowKES 25,234.08All of it kept in investments");
  expect(now).toHaveAttribute("href", "/admin/investments");
});
