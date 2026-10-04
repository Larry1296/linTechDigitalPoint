import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["accounting.view_moneycheck", "accounting.add_moneycheck", "accounting.add_cashentry"] } }) }));
import { api } from "../../core/api/client";
import { MoneyCheckPage, differenceText } from "./MoneyCheckPage";

const cash = { method: "CASH", label: "Cash in the drawer", expected: "5100.00", last_check: null, parts: [
  { key: "starting", label: "Starting money", amount: "5000.00" }, { key: "received", label: "Received from customers (less refunds)", amount: "300.00" },
  { key: "expenses", label: "Spent on running costs", amount: "-200.00" }, { key: "suppliers", label: "Paid to suppliers", amount: "0" }, { key: "loans", label: "Money lent, less repayments", amount: "0" }] };
beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path, options) => (options?.method === "POST"
    ? { id: 1, method: "CASH", expected: "5100.00", actual: "5070.00", difference: "-30.00" } : { places: [cash], history: [] }));
});

it("shows what the app expects and how, then compares a note-by-note count", async () => {
  render(<MemoryRouter><MoneyCheckPage /></MemoryRouter>);
  const place = await screen.findByRole("region", { name: "Cash in the drawer" });
  expect(within(place).getByText("Spent on running costs").nextSibling).toHaveTextContent("− KSh 200.00");
  fireEvent.change(within(place).getByLabelText("Number of 1000 notes"), { target: { value: "5" } });
  fireEvent.change(within(place).getByLabelText("Number of 50 notes"), { target: { value: "1" } });
  fireEvent.change(within(place).getByLabelText("Coins total"), { target: { value: "20" } });
  expect(within(place).getByText(/KSh 30.00 less than the app expected/)).toBeInTheDocument();
  fireEvent.click(within(place).getByRole("button", { name: "Save this count" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/accounting/money-check/", expect.objectContaining({ method: "POST" })));
  expect(JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body)).toMatchObject({ method: "CASH", actual: "5070.00", cash_count: { 1000: 5, 50: 1 } });
});

it("says plainly when the money matches", () => {
  expect(differenceText("0")).toBe("Exactly what the app expected.");
});
