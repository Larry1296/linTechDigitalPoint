import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true), askForm: vi.fn(async () => ({ reason: "Entered twice" })) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [
  "accounting.view_investment", "accounting.add_investment", "accounting.add_investmentmovement", "accounting.reverse_cashentry"] } }) }));
import { api } from "../../core/api/client";
import { InvestmentsPage } from "./InvestmentsPage";

const LOW = { code: "MMF", label: "Money market fund", risk: 1, risk_label: "Low", risk_note: "Short-term loans to the government and banks." };
const mmf = { id: 3, name: "Sanlam MMF", account_number: "MMF-0042", notes: "", value: "20150.00", put_in: "20000.00", taken_out: "0.00",
  interest: "150.00", fees: "0.00", tax_rate: "15.00", check_due: false, kind: LOW,
  current_rate: { month: "2026-10-01", label: "October 2026", annual_rate: "12.000", statement_balance: null, recorded_on: "2026-10-01", recorded_by: "Owner" },
  rates: [{ month: "2026-10-01", label: "October 2026", annual_rate: "12.000", statement_balance: null, recorded_on: "2026-10-01", recorded_by: "Owner" }],
  estimate: { since: "2026-09-30", days: 2, rate: "12.000", gross: "13.25", tax: "1.99", net: "11.26", value: "20161.26" },
  daily: [{ date: "2026-10-02", rate: "12.000", invested: "19000.00", moved: "0.00", interest: "5.63", statement: false, interest_so_far: "1161.26", value: "20161.26" },
    { date: "2026-10-01", rate: "12.000", invested: "19000.00", moved: "-1000.00", interest: "5.63", statement: false, interest_so_far: "1155.63", value: "20155.63" },
    { date: "2026-09-01", rate: "12.000", invested: "20000.00", moved: "20000.00", interest: "0.00", statement: false, interest_so_far: "0.00", value: "20000.00" }], fund: null,
  statements: [{ id: 8, date: "2026-09-30", label: "September 2026", since: "2026-09-01", statement_balance: "20150.00", predicted: "167.67", actual: "150.00", difference: "-17.67" }],
  earning: { balance: "20161.26", annual_rate: "12.000", estimated_balance: true, day: { gross: "6.63", tax: "0.99", net: "5.64" },
    month: { gross: "201.61", tax: "30.24", net: "171.37" }, year: { gross: "2554.10", tax: "383.12", net: "2170.98" } }, movements: [
    { id: 8, kind: "INTEREST", amount: "150.00", occurred_on: "2026-09-30", source: "", reference: "", note: "", statement_balance: "20150.00", reversed_at: null },
    { id: 9, kind: "WITHDRAWAL", amount: "5000.00", occurred_on: "2026-09-20", source: "MPESA", reference: "INV-77", note: "", statement_balance: null, reversed_at: null,
      purchase: { id: 4, receipt_number: "INV-77", supplier: "Phone Hub" } },
    { id: 7, kind: "DEPOSIT", amount: "20000.00", occurred_on: "2026-09-01", source: "AGENCY_CASH", reference: "", note: "", statement_balance: null, reversed_at: null }] };
const session = { id: 5, outlet: "Main agency", cash: "45000.00", float: "30000.00" };

const KINDS = [LOW, { code: "SACCO", label: "Sacco deposits", risk: 2, risk_label: "Low to medium", risk_note: "Depends on how the Sacco is managed." }];
const FUNDS = [{ code: "CIC_MMF_KES", name: "CIC Money Market Fund (KES)", short: "CIC", kind: LOW, annual_rate: "8.120" },
  { code: "KCB_MMF_KES", name: "KCB Money Market Fund (KES)", short: "KCB", kind: LOW, annual_rate: null }];
const listing = (investment) => ({ investments: [investment], total_value: "20150.00", worth_today: investment.estimate?.value ?? "20150.00", interest_earned: "150.00", estimated_interest: "11.26", this_month: "October 2026", agency_sessions: [session],
    funds: FUNDS, kinds: KINDS, earning: { day: investment.earning?.day.net ?? "0", month: investment.earning?.month.net ?? "0", year: investment.earning?.year.net ?? "0" },
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
  const rows = within(within(card).getByRole("table", { name: "History" })).getAllByRole("row");
  expect(rows[1]).toHaveTextContent("Interest");
  expect(rows[2]).toHaveTextContent("Taken out · paid for stock INV-77 (Phone Hub)");
  expect(rows[3]).toHaveTextContent("Put in");
  expect(rows[3]).toHaveTextContent("M-Pesa agency cash");
});

it("puts spare agency cash into the MMF through the open shift", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  fireEvent.click(within(card).getByRole("button", { name: "Add money" }));
  const form = within(card).getByRole("form", { name: "Add money" });
  fireEvent.change(within(form).getByLabelText(/Amount/), { target: { value: "10000" } });
  fireEvent.change(within(form).getByLabelText("Taken from"), { target: { value: "AGENCY_CASH" } });
  expect(within(form).getByText(/Main agency now: cash KSh 45,000/)).toBeInTheDocument();
  expect(within(form).queryByLabelText("Date the money went in")).toBeNull();
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record money added" })); });
  const [, options] = api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/move/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ kind: "DEPOSIT", amount: "10000", source: "AGENCY_CASH" }));
});

it("puts in the owner's own money from outside, of any amount, without a warning", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  fireEvent.click(within(card).getByRole("button", { name: "Add money" }));
  const form = within(card).getByRole("form", { name: "Add money" });
  fireEvent.change(within(form).getByLabelText(/Amount/), { target: { value: "900000" } });
  fireEvent.change(within(form).getByLabelText("Money source"), { target: { value: "OWN" } });
  expect(within(form).queryByLabelText("Taken from")).toBeNull();
  expect(within(form).getByText(/Nothing is taken from the business/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Date the money went in"), { target: { value: "2026-08-15" } });
  expect(within(form).queryByText(/more than the/)).toBeNull();
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record money added" })); });
  const [, options] = api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/move/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ kind: "DEPOSIT", amount: "900000", source: "OWNER", occurred_on: "2026-08-15" }));
  expect(JSON.parse(options.body)).not.toHaveProperty("origin");
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

it("removes an investment recorded by mistake, undoing everything in it", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  await act(async () => { fireEvent.click(within(card).getByRole("button", { name: "Remove this investment" })); });
  const [, options] = api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/remove/");
  expect(JSON.parse(options.body)).toEqual({ reason: "Entered twice" });
});

it("offers the till's spare money for investing, filled in and warned when it is more than expected", async () => {
  render(<InvestmentsPage />);
  const spare = await screen.findByRole("region", { name: "Money you could invest" });
  expect(within(spare).queryByText("Cash in the drawer")).toBeNull();  // nothing there
  expect(within(spare).getByText("Lipa na M-Pesa till").nextSibling).toHaveTextContent("KSh 64,000");
  fireEvent.click(within(spare).getByRole("button", { name: "Invest" }));
  const form = screen.getByRole("form", { name: "Add money" });
  expect(within(form).getByLabelText(/Amount/)).toHaveValue(64000);
  expect(within(form).getByLabelText("Taken from")).toHaveValue("MPESA");
  fireEvent.change(within(form).getByLabelText(/Amount/), { target: { value: "70000" } });
  expect(within(form).getByText(/more than the KSh 64,000 the app expects/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText(/Amount/), { target: { value: "50000" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record money added" })); });
  const [, options] = api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/3/move/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ kind: "DEPOSIT", amount: "50000", source: "MPESA" }));
});

it("shows the rate, the interest estimated since the statement and what the money earns a day, a month and a year", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  expect(within(card).getByText("12% a year · October 2026")).toBeInTheDocument();
  expect(within(card).getByText(/Estimated since/).nextSibling).toHaveTextContent("+ KSh 11.26 after 15% tax");
  expect(within(card).getByText("Estimated value today").nextSibling).toHaveTextContent("KSh 20,161.26");
  const earns = within(card).getByRole("region", { name: "What Sanlam MMF earns" });
  expect(earns).toHaveTextContent("At 12% a year, KSh 20,161.26 (estimated value today) earns after tax:");
  expect(within(earns).getByText("A day").nextSibling).toHaveTextContent("KSh 5.64KSh 6.63 before 15% tax");
  expect(within(earns).getByText("A month").nextSibling).toHaveTextContent("KSh 171.37");
  expect(within(earns).getByText("A year").nextSibling).toHaveTextContent("KSh 2,170.98");
  expect(screen.getByText("Worth today, with interest").nextSibling).toHaveTextContent("KSh 20,161.26");
  const daily = within(card).getByText(/^Day by day/).closest("details");
  expect(daily).toHaveTextContent(/Day by day since .+: KSh 19,000 invested, worth KSh 20,161.26 today/);
  const rows = within(daily).getAllByRole("row");
  expect(rows[1]).toHaveTextContent(/KSh 19,000.*\+ KSh 5.63.*KSh 1,161.26.*KSh 20,161.26/);
  expect(rows[2]).toHaveTextContent("KSh 19,000 · − KSh 1,000 taken out");
  expect(rows[3]).toHaveTextContent("KSh 20,000 · + KSh 20,000 put in");
  expect(screen.getByText("Earning now, after tax").nextSibling).toHaveTextContent("KSh 5.64 a day");
  expect(within(card).getByText(/entered by hand/)).toBeInTheDocument();
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

const cic = { ...mmf, id: 4, name: "CIC MMF", check_due: false, estimate: null,
  earning: { balance: "20150.00", annual_rate: "8.120", estimated_balance: false, day: { gross: "4.48", tax: "0.67", net: "3.81" },
    month: { gross: "136.35", tax: "20.45", net: "115.90" }, year: { gross: "1666.25", tax: "249.94", net: "1416.31" } },
  fund: { code: "CIC_MMF_KES", name: "CIC Money Market Fund (KES)", short: "CIC", annual_rate: "8.120", effective_annual_rate: "8.430",
    as_of: "2026-10-10", checked_on: "2026-10-10", next_check_on: "2026-10-20", source_url: "https://ke.cicinsurancegroup.com/investment/",
    fresh: true, can_check_now: false } };

it("follows CIC's published rate by itself, with no monthly rate check", async () => {
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : listing(cic)));
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "CIC MMF" })).closest("li");
  expect(within(card).getByText("8.12% a year · CIC rate, automatic")).toBeInTheDocument();
  const source = within(card).getByText(/CIC's published rate/).closest("p");
  expect(source).toHaveTextContent("Rate: CIC's published rate, 8.12% a year (8.43% with monthly interest added), as of");
  expect(source).toHaveTextContent(/Checked .+; next check by .+\./);
  expect(within(card).queryByRole("button", { name: "Monthly check" })).toBeNull();
  expect(within(card).getByRole("button", { name: "Update from statement" })).toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: /Check CIC's rate now/ })).toBeNull();  // the rate is current
  expect(within(screen.getByRole("region", { name: "What could it earn?" })).getByLabelText("Yearly rate (%)")).toHaveValue(8.12);
  await act(async () => { fireEvent.click(within(card).getByRole("button", { name: "Enter the rate myself instead" })); });
  expect(JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/accounting/investments/4/fund/")[1].body)).toEqual({ fund: "" });
});

it("starts a check of CIC's rate on request when it is missing", async () => {
  const waiting = { ...cic, earning: null, fund: { ...cic.fund, annual_rate: null, effective_annual_rate: null, as_of: null, checked_on: null,
    next_check_on: null, fresh: false, can_check_now: true } };
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? { started: true, fund: waiting.fund } : listing(waiting)));
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "CIC MMF" })).closest("li");
  expect(within(card).getByText(/The app is getting its current rate/)).toBeInTheDocument();
  await act(async () => { fireEvent.click(within(card).getByRole("button", { name: "Check CIC's rate now" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/accounting/investments/funds/CIC_MMF_KES/check/", { method: "POST" });
  expect(within(card).getByRole("status")).toHaveTextContent("Checking CIC's current rate. It shows here in a minute or two.");
});

it("asks whether money goes into an investment already held or a new one", async () => {
  render(<InvestmentsPage />);
  fireEvent.click((await screen.findAllByRole("button", { name: "Add money" }))[0]);  // the one at the top
  const chooser = screen.getByRole("form", { name: "Add money to" });
  expect(within(chooser).getByLabelText(/Sanlam MMF · KSh 20,161.26 now · 12% a year · low risk/)).toBeChecked();
  fireEvent.click(within(chooser).getByRole("button", { name: "Continue" }));
  const card = screen.getByRole("heading", { name: "Sanlam MMF" }).closest("li");
  expect(within(card).getByRole("form", { name: "Add money" })).toBeInTheDocument();
  expect(within(card).getByText(/Low risk · 1 of 5/)).toBeInTheDocument();
});

it("adds money to a new investment in a fund the app follows, its rate and risk shown", async () => {
  const kcb = { ...mmf, id: 11, name: "KCB MMF", movements: [], daily: [], estimate: null, earning: null };
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? kcb : { ...listing(mmf), investments: [mmf, kcb] }));
  render(<InvestmentsPage />);
  fireEvent.click((await screen.findAllByRole("button", { name: "Add money" }))[0]);  // the one at the top
  const chooser = screen.getByRole("form", { name: "Add money to" });
  fireEvent.click(within(chooser).getByLabelText(/A new investment/));
  fireEvent.click(within(chooser).getByRole("button", { name: "Continue" }));
  const form = screen.getByRole("form", { name: "New investment" });
  expect(within(form).getByRole("option", { name: "CIC Money Market Fund (KES) · 8.12% a year now" })).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Where are you investing?"), { target: { value: "KCB_MMF_KES" } });
  expect(within(form).getByLabelText("Name of the fund or account")).toHaveValue("KCB MMF");
  expect(within(form).getByText(/Low risk/)).toBeInTheDocument();
  expect(within(form).getByText(/reads KCB's rate on its own website now/)).toBeInTheDocument();
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Next: the amount" })); });
  const [, options] = api.mock.calls.find(([p, o]) => p === "/api/v1/accounting/investments/" && o?.method === "POST");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ name: "KCB MMF", fund: "KCB_MMF_KES", kind: "MMF", annual_rate: null }));
  const card = screen.getByRole("heading", { name: "KCB MMF" }).closest("li");
  expect(within(card).getByRole("form", { name: "Add money" })).toBeInTheDocument();
});

it("shows the risk of another kind of account, chosen when it is added", async () => {
  render(<InvestmentsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add investment account" }));
  const form = screen.getByRole("form", { name: "New investment" });
  fireEvent.change(within(form).getByLabelText("What kind is it?"), { target: { value: "SACCO" } });
  expect(within(form).getByText(/Low to medium risk · 2 of 5/)).toBeInTheDocument();
});

it("suggests following CIC's rate when a new account is named after it", async () => {
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : listing(mmf)));
  render(<InvestmentsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add investment account" }));
  const name = screen.getByLabelText("Name of the fund or account");
  const rate = screen.getByLabelText("Where are you investing?");
  expect(rate).toHaveValue("");
  expect(screen.getByLabelText(/Yearly interest rate it pays now/)).toBeInTheDocument();
  fireEvent.change(name, { target: { value: "CIC MMF" } });
  expect(rate).toHaveValue("CIC_MMF_KES");
  expect(screen.queryByLabelText(/Yearly interest rate it pays now/)).toBeNull();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add account" })); });
  const [, options] = api.mock.calls.find(([p, o]) => p === "/api/v1/accounting/investments/" && o?.method === "POST");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ name: "CIC MMF", fund: "CIC_MMF_KES", annual_rate: null }));
});

it("shows each statement next to the interest the app predicted for it", async () => {
  render(<InvestmentsPage />);
  const card = (await screen.findByRole("heading", { name: "Sanlam MMF" })).closest("li");
  const table = within(card).getByRole("table", { name: "What the app predicted, next to what the statement showed" });
  const row = within(table).getAllByRole("row")[1];
  expect(row).toHaveTextContent("+ KSh 167.67");
  expect(row).toHaveTextContent("+ KSh 150");
  expect(row).toHaveTextContent("− KSh 17.67");
});
