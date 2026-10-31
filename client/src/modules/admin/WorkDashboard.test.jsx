import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { first_name: "Jane", roles: ["EMPLOYEE"] } }) }));
vi.mock("../../core/data/liveRefresh", () => ({ useLiveRefresh: () => {} }));
vi.mock("./StockQuickSearch", () => ({ StockQuickSearch: () => null }));
import { api } from "../../core/api/client";
import { DashboardPage } from "./DashboardPage";

it("gives an employee their own dashboard: their pages and today's work, never the business's money", async () => {
  api.mockResolvedValue({ name: "Jane", business: "Corner shop", pages: [{ key: "sales", label: "Selling" }, { key: "mpesa", label: "M-Pesa agency" }],
    sales: { mine_today: 4 }, mpesa: { shift_open: true, transactions: 12 },
    low_stock: { count: 1, items: [{ name: "Phone charger", available: "2.000", minimum: "5.000" }] } });
  render(<MemoryRouter><DashboardPage /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Hello, Jane" })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/v1/inventory/dashboard/work/");
  expect(screen.getByRole("link", { name: "Record a sale" })).toHaveAttribute("href", "/admin/pos");
  expect(screen.getByRole("link", { name: "M-Pesa agent desk" })).toHaveAttribute("href", "/admin/mpesa");
  expect(screen.getByText("4 sales")).toBeInTheDocument();
  expect(screen.getByText("12 transactions recorded by you")).toBeInTheDocument();
  expect(screen.getByText("Phone charger")).toBeInTheDocument();
  expect(screen.queryByText(/profit|KES|KSh/i)).toBeNull();
});
