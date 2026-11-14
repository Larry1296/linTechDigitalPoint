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
  const card = screen.getByRole("region", { name: "What the business has brought in" });
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
  expect(within(card).getByText(/KES 600.00 \+ KES 20.00 \+ KES 700.00 \+ KES 250.00 =/)).toBeInTheDocument();
  expect(within(card).getByText(/Includes KES 300.00 sold on credit/)).toBeInTheDocument();
});

test("shows nothing when the viewer may see no part of the business", () => {
  const { container } = render(<SoldSummary sold={null} money={money} />);
  expect(container).toBeEmptyDOMElement();
});
