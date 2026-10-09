import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";
import { api } from "../../core/api/client";
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { organization: { id: 1 } } }) }));
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
const snapshot = () => ({
  organization: { id: 1, name: "Alpha Services", business_type: "SERVICES", currency: "KES", timezone: "Africa/Nairobi" },
  generated_at: "2026-09-21T09:00:00Z", business_date: "2026-09-21", financial_scope: "enabled_operations",
  today: { revenue: "120", cogs: null, expenses: null, profit: null, sales: 1, items_sold: 2 },
  business_units: [{ key: "CYBER", name: "Services", enabled: true, revenue: "120", profit: null, expenses: null }],
  cyber: { active_jobs: 2, ready_jobs: 1, jobs_today: 3 }, inventory: { restricted: true }, orders: { restricted: true }, mpesa: {},
  financial_trend: [{ month: "2026-09", sales: "120", profit: null, purchases: null, cogs: null, expenses: null }],
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });
it("shows the active business operations without drawing restricted profit", async () => {
  api.mockResolvedValue(snapshot());
  render(<DashboardPage />);
  expect(await screen.findByRole("heading", { name: "Alpha Services" })).toBeInTheDocument();
  expect(screen.queryByText("Current inventory")).not.toBeInTheDocument();
  expect(screen.queryByText("Everything in one place")).not.toBeInTheDocument();
  expect(document.querySelector(".trendProfit")).toBeNull();
});
it("refreshes figures, reports stale data and recovers", async () => {
  vi.useFakeTimers();
  api.mockResolvedValue(snapshot());
  render(<DashboardPage />);
  await act(async () => {});
  api.mockRejectedValueOnce(new Error("Offline"));
  await act(async () => { vi.advanceTimersByTime(15000); });
  expect(screen.getByRole("status")).toHaveTextContent("Can't update right now");
  api.mockResolvedValue({ ...snapshot(), today: { ...snapshot().today, revenue: "250" } });
  await act(async () => { vi.advanceTimersByTime(15000); });
  expect(screen.getByRole("status")).not.toHaveTextContent("Can't update right now");
  expect(screen.getByText("KES 250.00")).toBeInTheDocument();
  cleanup();
  const calls = api.mock.calls.length;
  await act(async () => { vi.advanceTimersByTime(15000); });
  expect(api).toHaveBeenCalledTimes(calls);
});

it("shows purchase and expense totals and requests the selected report period", async () => {
  api.mockResolvedValue({ ...snapshot(),
    period_summary: { start: "2026-09-01", end: "2026-09-21", purchases: "200", opening_stock: "180", revenue: "200", cogs: "80", gross_profit: "120", expenses: "50", profit: "70" },
    expense_breakdown: [{ category: "Rent", business_unit: "CYBER", amount: "50" }],
  });
  render(<DashboardPage />);
  expect(await screen.findByRole("heading", { name: "Running costs" })).toBeInTheDocument();
  expect(screen.getByText("Stock bought from suppliers")).toBeInTheDocument();
  expect(screen.getByRole("rowheader", { name: "Rent" })).toBeInTheDocument();
  expect(screen.getByText("KES 70.00 profit")).toBeInTheDocument();
  // The profit is shown as a sum anyone can check: sales − cost of what was sold − running costs.
  expect(screen.getByText("Sales KES 200.00 − what the sold items cost you KES 80.00 − running costs KES 50.00 = KES 70.00 profit")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-09-10" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply dates" }));
  await waitFor(() => expect(api).toHaveBeenLastCalledWith("/api/v1/inventory/dashboard/?start=2026-09-10&end=2026-09-21"));
});

it("shows profit with the M-Pesa commission Safaricom has not paid yet", async () => {
  api.mockResolvedValue({ ...snapshot(),
    period_summary: { start: "2026-10-01", end: "2026-10-09", purchases: "0", opening_stock: "0", revenue: "200", cogs: "80", gross_profit: "120", expenses: "150", profit: "-30" },
    mpesa_unpaid: { amount: "1250", months: ["October 2026"], profit_with: "1220" },
  });
  render(<DashboardPage />);
  const note = await screen.findByRole("note");
  expect(note).toHaveTextContent("M-Pesa commission not paid yet: about KES 1,250.00 earned in October 2026");
  expect(note).toHaveTextContent("Profit or loss with it: KES 1,220.00 profit");
});
