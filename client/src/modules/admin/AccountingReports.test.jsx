import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AccountingReportsPage } from "./AccountingReportsPage";
import { ExplainProfitPanel } from "./ExplainProfitPanel";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { branch: { id: 1 }, branches: [{ id: 1, name: "Main" }], permissions: [] } }) }));
beforeEach(() => vi.clearAllMocks());

const field = (amount, explain = "") => ({ amount, explain });
const owner = { view: "owner", currency: "KES", summary: {
  sales: field("3600"), money_received: field("2600"), stock_cost: field("2700"), gross_profit: field("900"), expenses: field("1300"),
  net_profit: { amount: "-400", loss: true, explain: "Gross profit minus expenses." },
  position: { cash_and_bank: "1300", customers_owe_you: "1000", you_owe_suppliers: "0", unpaid_bills: "0", tax_owed: "0", stock_value: "600" },
  warnings: [{ key: "uncosted_sales", amount: "900", quantity: "1", message: "Sales of stock whose buying price was never recorded." }] } };

it("shows the owner summary with money received kept apart from profit, a clear LOSS and warnings", async () => {
  api.mockResolvedValue(owner);
  render(<MemoryRouter><AccountingReportsPage /></MemoryRouter>);
  expect(await screen.findByText("Money received")).toBeInTheDocument();
  expect(screen.getByText(/KES\s?400\.00 loss/)).toHaveClass("lossText");
  expect(screen.getByText(/buying price was never recorded/)).toBeInTheDocument();
  expect(api.mock.calls[0][0]).toMatch(/view=owner/);
  api.mockResolvedValue({ view: "units", currency: "KES", warnings: [], profit_and_loss: { units: [
    { key: "retail", name: "Retail shop", revenue: "3600", direct_costs: "2700", gross_profit: "900" }], revenue: "3600", direct_costs: "2700",
    gross_profit: "900", operating_expenses: [{ code: "6000-1", name: "Rent", amount: "1000" }], total_operating_expenses: "1000", net_profit_before_tax: "-100", loss: true } });
  await act(async () => { fireEvent.click(screen.getByRole("tab", { name: "By business" })); });
  expect(await screen.findByText("Retail shop")).toBeInTheDocument();
  expect(screen.getByText("Rent")).toBeInTheDocument();
});

it("explains a sale line down to the delivery it came from and its journals", async () => {
  api.mockResolvedValue({
    sale: { number: "S-9", date: "2026-09-24T10:00:00Z", customer: "Walk-in", payment_status: "PAID", branch: "Main", cashier: "owner" },
    line: { item: "Router — AC1200", quantity: "2", catalogue_price: "1000", actual_price: "700", gross: "1400", discount: "0", discount_reason: "",
            tax: "0", net_revenue: "1400", cogs: "1050", gross_profit: "350", loss: false, cost_pending: false, returned_quantity: "0", formula: "gross profit = net revenue − COGS" },
    cost_layers: [{ delivery: "INV-1", supplier: "Tech Supplies", received_at: "2026-09-20", buying_price: "500", landed_cost_per_unit: "0", unit_cost: "500", quantity: "1", cost: "500", uncosted: false },
                  { delivery: "INV-2", supplier: "Tech Supplies", received_at: "2026-09-21", buying_price: "550", landed_cost_per_unit: "0", unit_cost: "550", quantity: "1", cost: "550", uncosted: false }],
    returns: [], notes: [], journals: [{ id: 1, date: "2026-09-24", description: "Sale S-9", lines: [{ account: "4000", name: "Retail sales", debit: "0", credit: "1400" }] }],
  });
  render(<ExplainProfitPanel itemId={5} onClose={vi.fn()} />);
  expect(await screen.findByText("Router — AC1200")).toBeInTheDocument();
  expect(screen.getByText(/INV-2 · Tech Supplies/)).toBeInTheDocument();
  expect(screen.getByText("Sale S-9", { exact: false })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/v1/accounting/explain/sale-items/5/");
});
