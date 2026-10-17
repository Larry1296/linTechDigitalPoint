import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
import { api } from "../../core/api/client";
import { PartBooks } from "./PartBooks";

const books = { key: "SHOP", label: "Shop", since: "2026-09-01", count: 2,
  all_time: { revenue: "1500", cogs: "500", expenses: "200", stock_corrections: "0", profit: "800" },
  months: [{ month: "2026-10", revenue: "1500", cogs: "500", expenses: "200", stock_corrections: "0", profit: "800" }],
  money: { amount: "1300", places: [{ label: "Cash in the drawer", amount: "1100" }, { label: "Lipa na M-Pesa till", amount: "200" }] } };

it("shows the part's own sales, the items' buying price, running costs, its profit and its money", async () => {
  api.mockResolvedValue(books);
  render(<PartBooks part="SHOP" />);
  expect(await screen.findByRole("heading", { name: "Shop on its own" })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/v1/inventory/parts/SHOP/");
  expect(screen.getByText("Sales", { selector: "dt" }).nextSibling).toHaveTextContent("KSh 1,500");
  expect(screen.getByText("− What the sold items cost (buying price)").nextSibling).toHaveTextContent("KSh 500");
  expect(screen.getByText("Profit or loss", { selector: "dt" }).nextSibling).toHaveTextContent("KSh 800 profit");
  expect(screen.getByText("Shop's own money now").nextSibling).toHaveTextContent("KSh 1,300 · Cash in the drawer KSh 1,100 · Lipa na M-Pesa till KSh 200");
});

it("shows a loss as a loss and hides costs from someone who may not see profit", async () => {
  api.mockResolvedValue({ ...books, key: "CYBER", label: "Cyber", all_time: { ...books.all_time, cogs: null, expenses: null, profit: null }, money: null });
  render(<PartBooks part="CYBER" />);
  expect(await screen.findByText("Income from services", { selector: "dt" })).toBeInTheDocument();
  expect(screen.queryByText("Profit or loss", { selector: "dt" })).toBeNull();
  expect(screen.queryByText(/money now/)).toBeNull();
});
