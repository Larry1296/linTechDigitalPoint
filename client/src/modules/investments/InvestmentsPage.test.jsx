import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true), askForm: vi.fn(async () => ({ reason: "Entered twice" })) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [
  "accounting.view_investment", "accounting.add_investment", "accounting.add_investmentmovement", "accounting.reverse_cashentry"] } }) }));
import { api } from "../../core/api/client";
import { InvestmentsPage } from "./InvestmentsPage";

const mmf = { id: 3, name: "Sanlam MMF", account_number: "MMF-0042", notes: "", value: "20150.00", put_in: "20000.00", taken_out: "0.00",
  interest: "150.00", fees: "0.00", tax_rate: "15.00", check_due: false,
  current_rate: { month: "2026-10-01", label: "October 2026", annual_rate: "12.000", statement_balance: null, recorded_on: "2026-10-01", recorded_by: "Owner" },
  rates: [{ month: "2026-10-01", label: "October 2026", annual_rate: "12.000", statement_balance: null, recorded_on: "2026-10-01", recorded_by: "Owner" }],
  estimate: { since: "2026-09-30", days: 2, rate: "12.000", gross: "13.25", tax: "1.99", net: "11.26", value: "20161.26" }, movements: [
    { id: 8, kind: "INTEREST", amount: "150.00", occurred_on: "2026-09-30", source: "", reference: "", note: "", statement_balance: "20150.00", reversed_at: null },
    { id: 9, kind: "WITHDRAWAL", amount: "5000.00", occurred_on: "2026-09-20", source: "MPESA", reference: "INV-77", note: "", statement_balance: null, reversed_at: null,
      purchase: { id: 4, receipt_number: "INV-77", supplier: "Phone Hub" } },
    { id: 7, kind: "DEPOSIT", amount: "20000.00", occurred_on: "2026-09-01", source: "AGENCY_CASH", reference: "", note: "", statement_balance: null, reversed_at: null }] };
const session = { id: 5, outlet: "Main agency", cash: "45000.00", float: "30000.00" };

const listing = (investment) => ({ investments: [investment], total_value: "20150.00", interest_earned: "150.00", estimated_interest: "11.26", this_month: "October 2026", agency_sessions: [session],
    spare_money: [{ method: "CASH", label: "Cash in the drawer", expected: "0.00" }, { method: "MPESA", label: "Lipa na M-Pesa till", expected: "64000.00" }] });
beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : listing(mmf)));
});

it("shows what the MMF holds, what went in and the interest, with dated history", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  expect(screen.getByText("Invested now").nextSibling).toHaveTextContent("KSh 20,150");
  expect(screen.getByText("Interest earned (after fees)").nextSibling).toHaveTextContent("KSh 150");
  expect(within(card).getByText("Recorded value").nextSibling).toHaveTextContent("KSh 20,150");
  expect(within(card).getByText("Interest earned").nextSibling).toHaveTextContent("KSh 150");
  const rows = within(card).getAllByRole("row");
  expect(rows[1]).toHaveTextContent("Interest");
  expect(rows[2]).toHaveTextContent("Taken out · paid for stock INV-77 (Phone Hub)");
  expect(rows[3]).toHaveTextContent("Put in");
  expect(rows[3]).toHaveTextContent("M-Pesa agency cash");
});

it("puts spare agency cash into the MMF through the open shift", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  fireEvent.click(within(card).getByRole("button", { name: "Put money in" }));
  const form = within(card).getByRole("form", { name: "Put money in" });
  fireEvent.change(within(form).getByLabelText(/Amount/), { target: { value: "10000" } });
  fireEvent.change(within(form).getByLabelText("Taken from"), { target: { value: "AGENCY_CASH" } });
  expect(within(form).getByText(/Main agency now: cash KSh 45,000/)).toBeInTheDocument();
  expect(within(form).queryByLabelText("Date")).toBeNull();
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record money put in" })); });
  const [, options] = api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/move/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ kind: "DEPOSIT", amount: "10000", source: "AGENCY_CASH" }));
});

it("records a statement balance and can undo a mistake", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  fireEvent.click(within(card).getByRole("button", { name: "Update from statement" }));
  const form = within(card).getByRole("form", { name: "Record statement balance" });
  fireEvent.change(within(form).getByLabelText(/Balance on the statement/), { target: { value: "20300" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record statement" })); });
  expect(JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/statement/")[1].body)).toEqual(expect.objectContaining({ balance: "20300" }));
  await act(async () => { fireEvent.click(within(card).getAllByRole("button", { name: "Undo" })[0]); });
  expect(JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/movements/8/undo/")[1].body)).toEqual({ reason: "Entered twice" });
});

it("offers the till's spare money for investing, filled in and warned when it is more than expected", async () => {
  render(<InvestmentsPage />);
  const spare = await screen.findByRole("region", { name: "Money you could invest" });
  expect(within(spare).queryByText("Cash in the drawer")).toBeNull();  // nothing there
  expect(within(spare).getByText("Lipa na M-Pesa till").nextSibling).toHaveTextContent("KSh 64,000");
  fireEvent.click(within(spare).getByRole("button", { name: "Invest" }));
  const form = screen.getByRole("form", { name: "Put money in" });
  expect(within(form).getByLabelText(/Amount/)).toHaveValue(64000);
  expect(within(form).getByLabelText("Taken from")).toHaveValue("MPESA");
  fireEvent.change(within(form).getByLabelText(/Amount/), { target: { value: "70000" } });
  expect(within(form).getByText(/more than the KSh 64,000 the app expects/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText(/Amount/), { target: { value: "50000" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record money put in" })); });
  const [, options] = api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/move/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ kind: "DEPOSIT", amount: "50000", source: "MPESA" }));
});

it("shows the rate, the interest estimated since the statement and what the money earns a day", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  expect(within(card).getByText("12% a year · October 2026")).toBeInTheDocument();
  expect(within(card).getByText(/Estimated since/).nextSibling).toHaveTextContent("+ KSh 11.26 after 15% tax");
  expect(within(card).getByText("Estimated value today").nextSibling).toHaveTextContent("KSh 20,161.26");
  expect(within(card).getByText(/earns about/)).toHaveTextContent("KSh 5.63 a day");  // 20,150 × 12% ÷ 365 × 85%
  expect(screen.queryByRole("status", { name: "Monthly check due" })).toBeNull();
});

it("prompts for the monthly check and records the rate with the statement balance", async () => {
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : listing({ ...mmf, check_due: true })));
  render(<InvestmentsPage />);
  const banner = await screen.findByRole("status", { name: "Monthly check due" });
  expect(banner).toHaveTextContent("Monthly check due for October 2026");
  fireEvent.click(within(banner).getByRole("button", { name: "Do the check" }));
  const form = screen.getByRole("form", { name: "Monthly check" });
  expect(within(form).getByLabelText(/Yearly rate/)).toHaveValue(12);
  expect(within(form).getByLabelText(/Balance on the statement/)).toHaveAttribute("placeholder", "About 20,161.26 expected");
  fireEvent.change(within(form).getByLabelText(/Yearly rate/), { target: { value: "12.5" } });
  fireEvent.change(within(form).getByLabelText(/Balance on the statement/), { target: { value: "20170" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record monthly check" })); });
  const [, options] = api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/monthly/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ annual_rate: "12.5", balance: "20170" }));
});

it("works out what an amount could earn, starting from the latest rate", async () => {
  render(<InvestmentsPage />);
  const calculator = await screen.findByRole("region", { name: "What could it earn?" });
  expect(within(calculator).getByLabelText("Yearly rate (%)")).toHaveValue(12);
  fireEvent.change(within(calculator).getByLabelText(/Amount to invest/), { target: { value: "100000" } });
  fireEvent.change(within(calculator).getByLabelText("For how long"), { target: { value: "1" } });
  expect(within(calculator).getByText("Interest after tax").nextSibling).toHaveTextContent("KSh 850");
  expect(within(calculator).getByText("Balance at the end").nextSibling).toHaveTextContent("KSh 100,850");
  expect(api.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(0);  // nothing is saved
});
