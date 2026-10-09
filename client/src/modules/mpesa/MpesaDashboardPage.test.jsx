import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["mpesa.add_mpesaoutlet", "mpesa.change_mpesaoutlet", "mpesa.delete_mpesaoutlet", "mpesa.reverse_mpesa_transaction"] } }) }));
vi.mock("./api", () => ({
  getMpesaDashboard: vi.fn(), getMpesaAnalysis: vi.fn(async () => ({ days: [], hours: [], sizes: [], commission_by_kind: [], working_days: 30, unknown: 0 })), getCommissionAdvice: vi.fn(async () => ({ earned: null, ask: true, reason: "new" })), getMpesaOutlets: vi.fn(), getMpesaTransactions: vi.fn(), createMpesaOutlet: vi.fn(),
  updateMpesaOutlet: vi.fn(), deleteMpesaOutlet: vi.fn(), getMpesaReportMonths: vi.fn(async () => []), getPastMpesaShifts: vi.fn(async () => []), getMpesaShiftTransactions: vi.fn(), downloadMpesaReport: vi.fn(), openMpesaSession: vi.fn(), postMpesaTransaction: vi.fn(), reconcileMpesaSession: vi.fn(), reverseMpesaTransaction: vi.fn(),
}));
import * as api from "./api";
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
import { MpesaDashboardPage } from "./MpesaDashboardPage";

const dashboard = { session: null, cash: 0, float: 0, deposits: 0, withdrawals: 0, transaction_count: 0, commission: 0, in_operation: { total: 0, opening: 0 } };
const outlet = (id, name, money) => ({ id, display_name: name, agent_reference: "123456", store_number: "654321", active: true, money_in_operation: money });

beforeEach(() => {
  api.getMpesaDashboard.mockResolvedValue(dashboard);
  api.getMpesaTransactions.mockResolvedValue([]);
  api.getMpesaOutlets.mockResolvedValue([
    outlet(1, "Main till", { cash: "3000.00", float: "7000.00", total: "10000.00", updated_on: "2026-09-26", due: false }),
    outlet(2, "Market till", { cash: "2000.00", float: "5000.00", total: "7000.00", updated_on: "2026-09-25", due: true }),
  ]);
});

it("always shows each outlet's numbers and money in operation, flagging a due update", async () => {
  render(<MpesaDashboardPage />);
  const main = (await screen.findByRole("heading", { name: "Main till" })).closest("li");
  expect(main).toHaveTextContent("123456");
  expect(main).toHaveTextContent("654321");
  expect(main).toHaveTextContent("10,000");
  expect(main).not.toHaveClass("due");
  const market = screen.getByRole("heading", { name: "Market till" }).closest("li");
  expect(market).toHaveClass("due");
  expect(within(market).getByRole("status")).toHaveTextContent("Update due");
});

it("keeps the add-outlet form behind a button", async () => {
  render(<MpesaDashboardPage />);
  const button = await screen.findByRole("button", { name: "Add outlet" });
  expect(screen.queryByLabelText("Store number")).not.toBeInTheDocument();
  fireEvent.click(button);
  expect(screen.getByLabelText("Agent number")).toBeInTheDocument();
  expect(screen.getByLabelText("Store number")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByLabelText("Store number")).not.toBeInTheDocument();
});


it("edits an outlet's name and numbers in place", async () => {
  api.updateMpesaOutlet.mockResolvedValue({});
  render(<MpesaDashboardPage />);
  const main = (await screen.findByRole("heading", { name: "Main till" })).closest("li");
  fireEvent.click(within(main).getByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Agent number")).toHaveValue("123456");
  fireEvent.change(screen.getByLabelText("Store number"), { target: { value: "999999" } });
  fireEvent.click(screen.getByRole("button", { name: "Save outlet" }));
  await waitFor(() => expect(api.updateMpesaOutlet).toHaveBeenCalledWith(1, { display_name: "Main till", agent_reference: "123456", store_number: "999999" }));
});

it("shows why an outlet with history cannot be deleted", async () => {
  api.deleteMpesaOutlet.mockRejectedValue(new Error("This outlet has shift history and cannot be deleted. Deactivate it instead."));
  render(<MpesaDashboardPage />);
  const market = (await screen.findByRole("heading", { name: "Market till" })).closest("li");
  fireEvent.click(within(market).getByRole("button", { name: "Delete" }));
  expect(await screen.findByText(/Deactivate it instead/)).toBeInTheDocument();
});


it("shows only the open shift's transactions, and none once no shift is open", async () => {
  const entry = (id, session) => ({ id, session, internal_reference: `MPA-${id}`, transaction_type: "CUSTOMER_DEPOSIT", amount: "500.00",
    cash_delta: "500.00", float_delta: "-500.00", occurred_at: new Date().toISOString(), customer_phone: "254712345678",
    customer_id_number: "12345678", provider_reference: null, reversal_of: null });
  api.getMpesaTransactions.mockResolvedValue([entry(1, 7), entry(2, 8)]);
  api.getMpesaDashboard.mockResolvedValue({ ...dashboard, session: { id: 8, opened_at: new Date().toISOString() }, cash: "1000", float: "1000" });
  const { unmount } = render(<MpesaDashboardPage />);
  expect(await screen.findByRole("heading", { name: "Deposits this shift (1)" })).toBeInTheDocument();
  expect(screen.getByText("MPA-2")).toBeInTheDocument();
  expect(screen.queryByText("MPA-1")).not.toBeInTheDocument();
  expect(screen.queryByText("COMMISSION")).not.toBeInTheDocument();
  unmount();
  api.getMpesaDashboard.mockResolvedValue(dashboard);
  render(<MpesaDashboardPage />);
  expect(await screen.findByRole("heading", { name: "Deposits this shift (0)" })).toBeInTheDocument();
  expect(screen.getByText("No shift open. Open a shift to start recording.")).toBeInTheDocument();
});

it("leaves a reversed transaction and its reversal out of every list", async () => {
  const at = new Date().toISOString();
  const base = { session: 8, occurred_at: at, customer_phone: "254712345678", customer_id_number: "12345678", provider_reference: null };
  api.getMpesaTransactions.mockResolvedValue([
    { ...base, id: 1, internal_reference: "MPA-KEPT", transaction_type: "CUSTOMER_DEPOSIT", amount: "500.00", cash_delta: "500", float_delta: "-500", reversal_of: null },
    { ...base, id: 2, internal_reference: "MPA-WRONG", transaction_type: "CUSTOMER_DEPOSIT", amount: "700.00", cash_delta: "700", float_delta: "-700", reversal_of: null },
    { ...base, id: 3, internal_reference: "MPR-UNDO", transaction_type: "REVERSAL", amount: "700.00", cash_delta: "-700", float_delta: "700", reversal_of: 2 },
  ]);
  api.getMpesaDashboard.mockResolvedValue({ ...dashboard, session: { id: 8, opened_at: at }, cash: "1500", float: "4500" });
  render(<MpesaDashboardPage />);
  expect(await screen.findByRole("heading", { name: "Deposits this shift (1)" })).toBeInTheDocument();
  expect(screen.getByText("MPA-KEPT")).toBeInTheDocument();
  expect(screen.queryByText("MPA-WRONG")).not.toBeInTheDocument();
  expect(screen.queryByText("MPR-UNDO")).not.toBeInTheDocument();
});

it("lets a manager correct the money in operation down, with a reason", async () => {
  api.getMpesaDashboard.mockResolvedValue({ ...dashboard, session: { id: 8, opened_at: new Date().toISOString() }, cash: "20000.00", float: "30000.00",
    in_operation: { total: "50000.00", opening: "50000.00" } });
  api.postMpesaTransaction.mockResolvedValue({});
  render(<MpesaDashboardPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Correct money in operation" }));
  const form = screen.getByRole("form", { name: "Correct money in operation" });
  expect(within(form).getByLabelText("Cash should be")).toHaveValue(20000);
  expect(within(form).getByRole("button", { name: "Correct money in operation" })).toBeDisabled();
  fireEvent.change(within(form).getByLabelText("Cash should be"), { target: { value: "15000" } });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Opening cash counted twice" } });
  expect(form).toHaveTextContent("(−5,000.00)");
  fireEvent.click(within(form).getByRole("button", { name: "Correct money in operation" }));
  await waitFor(() => expect(api.postMpesaTransaction).toHaveBeenCalled());
  expect(api.postMpesaTransaction.mock.calls[0][0]).toEqual(expect.objectContaining({ session: 8, transaction_type: "ADJUSTMENT", amount: "5000.00",
    cash_delta: "-5000.00", float_delta: "0.00", notes: "Opening cash counted twice" }));
});
