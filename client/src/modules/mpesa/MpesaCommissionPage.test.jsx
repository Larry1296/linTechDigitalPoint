import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true), askForm: vi.fn(async () => ({ reason: "Wrong amount" })) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["mpesa.view_mpesacommissionentry", "mpesa.add_mpesacommissionentry", "accounting.reverse_cashentry"] } }) }));
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";
import { MpesaCommissionPage } from "./MpesaCommissionPage";

const places = [["AGENCY_FLOAT", "Kept in the agency float (the float goes up)"], ["AGENCY_FLOAT_TO_OWNER", "Paid into the float, owner took it from the drawer as cash"],
  ["AGENCY_CASH", "Put into the agency cash drawer"], ["OPENING_FLOAT", "Already in the float when a shift opened"], ["MPESA", "Your own M-Pesa"], ["BANK", "Bank"], ["CASH", "Cash kept outside the agency"], ["OTHER", "Other"]];
const listing = (extra = {}) => ({ places, due_month: "2026-09-01", due_label: "September 2026", outlets: [{ id: 2, name: "Agent till", open_session: 9,
  opening_shifts: [{ id: 4, opened_on: "2026-10-05", opening_float: "11045", carried_float: null, room: "11045" }] }],
  totals: { commission: "4200", expenses: "1000", profit: "3200" },
  months: [{ month: "2026-08-01", label: "August 2026", commission: "0", expenses: "1500", profit: "-1500" },
    { month: "2026-09-01", label: "September 2026", commission: "4200", expenses: "1000", profit: "3200" }],
  entries: [{ id: 5, month: "September 2026", amount: "4200", paid_on: "2026-10-02", settlement_method: "MPESA", reference: "SJQ1COMM01", notes: "", reversed_at: null }], ...extra });

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : listing()));
});

it("reminds about last month and shows the agency's profit each month", async () => {
  render(<MpesaCommissionPage />);
  expect(await screen.findByRole("status", { name: "Commission due" })).toHaveTextContent("September 2026's commission is not recorded yet");
  expect(screen.getByText("Agency profit").nextSibling).toHaveTextContent("KSh 3,200");
  expect(screen.getByRole("row", { name: /August 2026/ })).toHaveTextContent("Loss KSh 1,500");
});

it("records commission paid into the float through today's open shift", async () => {
  render(<MpesaCommissionPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Record it" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  expect(within(form).getByLabelText("Month it was earned")).toHaveValue("2026-09");
  expect(within(form).queryByLabelText("Date it was paid")).toBeNull();  // agency money moves today, through the shift
  fireEvent.change(within(form).getByLabelText(/Amount Safaricom paid/), { target: { value: "4200" } });
  expect(within(form).queryByLabelText(/M-Pesa code/)).toBeNull();  // Safaricom gives no code for commission
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record commission" })); });
  expect(confirmAction.mock.calls[0][0].title).toBe("Record KSh 4,200 commission for September 2026?");
  const body = JSON.parse(api.mock.calls.find(([p, o]) => p === "/api/v1/mpesa/commission/" && o?.method === "POST")[1].body);
  expect(body).not.toHaveProperty("reference");
  expect(body).toEqual(expect.objectContaining({ outlet: 2, period: "2026-09-01", amount: "4200", settlement_method: "AGENCY_FLOAT", session_id: 9 }));
});

it("asks for the payment date when the money went elsewhere, and undoes a mistake with a reason", async () => {
  render(<MpesaCommissionPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Record it" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  fireEvent.change(within(form).getByLabelText("Where the money went"), { target: { value: "BANK" } });
  expect(within(form).getByLabelText("Date it was paid")).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Undo" })); });
  expect(JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/mpesa/commission/5/undo/")[1].body)).toEqual({ reason: "Wrong amount" });
});

it("will not record into the agency with no shift open", async () => {
  api.mockImplementation(async () => listing({ outlets: [{ id: 2, name: "Agent till", open_session: null }] }));
  render(<MpesaCommissionPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Record it" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  expect(within(form).getByText(/Open Agent till's shift first/)).toBeInTheDocument();
  expect(within(form).getByRole("button", { name: "Record commission" })).toBeDisabled();
});

it("records commission that was already in a shift's opening float against that shift", async () => {
  render(<MpesaCommissionPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Record it" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  fireEvent.change(within(form).getByLabelText("Where the money went"), { target: { value: "OPENING_FLOAT" } });
  expect(within(form).queryByLabelText("Date it was paid")).toBeNull();  // the day that shift opened
  expect(within(form).getByLabelText("Shift whose opening float had it")).toHaveTextContent("opened with float KSh 11,045");
  expect(form).toHaveTextContent("The float does not change");
  fireEvent.change(within(form).getByLabelText(/Amount Safaricom paid/), { target: { value: "1020" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record commission" })); });
  const body = JSON.parse(api.mock.calls.find(([p, o]) => p === "/api/v1/mpesa/commission/" && o?.method === "POST")[1].body);
  expect(body).toEqual(expect.objectContaining({ amount: "1020", settlement_method: "OPENING_FLOAT", session_id: 4, paid_on: "2026-10-05" }));
});

it("compares Safaricom's payment with the app's figure and records what was spent straight from it", async () => {
  vi.resetModules();
  const auth = await import("../../core/auth/AuthContext");
  vi.spyOn(auth, "useAuth").mockReturnValue({ user: { permissions: ["mpesa.view_mpesacommissionentry", "mpesa.add_mpesacommissionentry", "accounting.add_expense"] } });
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? {} : path.includes("accounting/categories") ? [{ id: 1, name: "Rent" }]
    : listing({ estimates: [{ month: "2026-09-01", label: "September 2026", current: false, earned: "4000", expected: "4000", unknown: 0, paid: null, difference: null }], learned: [] })));
  render(<MpesaCommissionPage />);
  expect(await screen.findByRole("row", { name: /September 2026 KSh 4,000 Not recorded yet/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Record it" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  fireEvent.change(within(form).getByLabelText(/Amount Safaricom paid/), { target: { value: "4200" } });
  expect(within(form).getByText(/The app worked out/)).toHaveTextContent("KSh 4,000 for September 2026");
  expect(within(form).getByText(/Safaricom paid KSh 200 more \(5%\)/)).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "+ Add something it was spent on" }));
  fireEvent.change(within(form).getByLabelText("Type of cost"), { target: { value: "Rent" } });
  fireEvent.change(within(form).getByLabelText("What for"), { target: { value: "Shop rent" } });
  fireEvent.change(within(form).getByLabelText(/^Amount \(KSh\)/), { target: { value: "3000" } });
  fireEvent.change(within(form).getByLabelText("For"), { target: { value: "SHOP" } });
  expect(within(form).getByText(/KSh 3,000 spent, KSh 1,200 goes to: kept in the agency float/)).toBeInTheDocument();
  expect(within(form).getByLabelText("Where the rest went")).toBeInTheDocument();
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record commission" })); });
  const body = JSON.parse(api.mock.calls.find(([path, options]) => path === "/api/v1/mpesa/commission/" && options?.method === "POST")[1].body);
  expect(body).toMatchObject({ amount: "4200", settlement_method: "AGENCY_FLOAT", spent: [{ category: "Rent", description: "Shop rent", amount: "3000", unit: "SHOP" }] });
});
