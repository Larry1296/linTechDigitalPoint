import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true), askForm: vi.fn() }));
vi.mock("../admin/PartBooks", () => ({ PartBooks: () => null }));
let permissions = ["mkopa.view_mkopasale", "mkopa.add_mkopasale", "mkopa.add_mkopastock"];
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions } }) }));
import { api } from "../../core/api/client";
import { MkopaPage } from "./MkopaPage";

const plan = (id, deposit, daily, days, commission, extra = {}) => ({ id, deposit, daily_payment: daily, days, total_price: String(deposit + daily * days), active: true,
  sold: 0, paid_phones: 0, received: "0", typed_commission: null, learned_commission: commission ?? null, learned_from: commission ? 2 : 0,
  commission_source: commission ? "LEARNED" : null, ...(commission !== undefined ? { commission } : {}), ...extra });
const sale = (id, phone, p, name, soldOn) => ({ id, phone, plan_id: p.id, customer_name: name, customer_phone: "", imei: "", sold_on: soldOn,
  deposit: p.deposit, daily_payment: p.daily_payment, days: p.days, commission: p.commission ?? null, commission_paid: false, reversed_at: null });
const owner = {
  phones: [{ id: 1, name: "X30", active: true, received: 3, sold: 1, in_hand: 2, tracks_stock: true, old_plans: [],
    plans: [plan(11, 3899, 93, 365, "1200"), plan(12, 5999, 130, 180, "1500")] },
  { id: 2, name: "X4", active: true, received: 0, sold: 0, in_hand: 0, tracks_stock: false, old_plans: [], plans: [plan(21, 2999, 60, 365, "900")] }],
  sales: [], stock: [], commissions: [], unpaid: [], methods: [["CASH", "Cash"], ["MPESA", "M-Pesa"], ["BANK", "Bank"], ["OTHER", "Other"]],
  can_see_money: true, can_set_up: true, can_undo: true, can_record_commission: true,
  summary: { phones_sold: 1, commission_earned: "1200", commission_paid: "0", commission_owed: "1200", unpaid_phones: 1, unknown_phones: 0, month_sold: 1, month_commission: "1200" },
};

beforeEach(() => {
  vi.clearAllMocks();
  permissions = ["mkopa.view_mkopasale", "mkopa.add_mkopasale", "mkopa.add_mkopastock"];
  api.mockImplementation(async (path, options) => (options?.method ? {} : owner));
});

it("shows each phone's plans with what the customer pays and the commission, and what M-KOPA still owes", async () => {
  render(<MkopaPage />);
  const x30 = await screen.findByRole("article", { name: "X30" });
  const rows = within(x30).getAllByRole("row").slice(1).map((row) => row.textContent);
  expect(rows[0]).toMatch(/3,899.*93.*365.*37,844.*1,200.*Learned from 2 payments/);
  expect(rows[1]).toMatch(/5,999.*130.*180.*29,399.*1,500/);
  expect(screen.getByText("M-KOPA still owes you").nextSibling).toHaveTextContent("1,200");
});

it("works out what selling more phones would earn", async () => {
  render(<MkopaPage />);
  const calculator = await screen.findByRole("region", { name: "What would I earn?" });
  fireEvent.change(within(calculator).getByLabelText(/How many X30 on KSh 3,899/), { target: { value: "4" } });
  fireEvent.change(within(calculator).getByLabelText(/How many X30 on KSh 5,999/), { target: { value: "2" } });
  expect(within(calculator).getByText("Total").closest("tr")).toHaveTextContent(/6 phones.*7,800/);
});

it("sells a phone on the plan the customer chose", async () => {
  render(<MkopaPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Sell a phone" }));
  fireEvent.change(screen.getByLabelText("Plan the customer chose"), { target: { value: "12" } });
  fireEvent.change(screen.getByLabelText("Customer's name"), { target: { value: "Mary Achieng" } });
  fireEvent.click(screen.getByRole("button", { name: "Record sale" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/mkopa/sales/", expect.objectContaining({ method: "POST" })));
  const body = JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body);
  expect(body).toMatchObject({ plan: 12, customer_name: "Mary Achieng" });
});

it("adds a new model with two plans, one commission known and one left to be filled in when M-KOPA pays", async () => {
  api.mockImplementation(async (path, options) => (options?.method ? { id: 5 } : { ...owner, phones: [] }));
  render(<MkopaPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add phones" }));
  const form = screen.getByRole("form", { name: "Add phones" });
  fireEvent.change(within(form).getByLabelText("Phone model"), { target: { value: "X4e" } });
  fireEvent.click(within(form).getByRole("button", { name: "+ Add a second plan" }));
  const fill = (index, label, value) => fireEvent.change(within(form).getAllByLabelText(label)[index], { target: { value } });
  [["3899", "93", "365", "1200"], ["5999", "130", "180", ""]].forEach(([d, p, n, c], i) => {
    fill(i, /Deposit/, d); fill(i, /Paid each day/, p); fill(i, "For how many days", n); fill(i, /Commission per phone/, c);
  });
  fireEvent.change(within(form).getByLabelText(/How many M-KOPA gave you/), { target: { value: "5" } });
  expect(within(form).getByText(/pays M-KOPA KSh 37,844 in all/)).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Add phone" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/mkopa/phones/", expect.objectContaining({ method: "POST" })));
  const body = JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body);
  expect(body).toEqual({ name: "X4e", plans: [{ deposit: "3899", daily_payment: "93", days: 365, commission: "1200" },
    { deposit: "5999", daily_payment: "130", days: 180, commission: null }] });
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/mkopa/stock/", expect.objectContaining({ method: "POST" })));
  expect(JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/mkopa/stock/")[1].body)).toMatchObject({ phone: 5, quantity: 5, kind: "RECEIVED" });
});

it("adds more phones of a model already sold, and another plan for it, without retyping its plans", async () => {
  render(<MkopaPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add phones" }));
  const form = screen.getByRole("form", { name: "Add phones" });
  expect(within(form).getByLabelText("A model I already sell")).toBeChecked();
  fireEvent.change(within(form).getByLabelText("Phone model"), { target: { value: "1" } });
  fireEvent.change(within(form).getByLabelText(/How many more M-KOPA gave you/), { target: { value: "3" } });
  fireEvent.click(within(form).getByRole("button", { name: "+ Add another plan for X30" }));
  const fill = (label, value) => fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  fill(/Deposit/, "7999"); fill(/Paid each day/, "150"); fill("For how many days", "120");
  fireEvent.click(within(form).getByRole("button", { name: "Add 3 phones" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/mkopa/stock/", expect.objectContaining({ method: "POST" })));
  const patch = JSON.parse(api.mock.calls.find(([path, o]) => path === "/api/v1/mkopa/phones/1/" && o?.method === "PATCH")[1].body);
  expect(patch.plans.map((p) => [p.id, p.deposit])).toEqual([[11, 3899], [12, 5999], [undefined, "7999"]]);
  expect(JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/mkopa/stock/")[1].body)).toMatchObject({ phone: 1, quantity: 3 });
});

it("says a new model typed is already in the list", async () => {
  render(<MkopaPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add phones" }));
  const form = screen.getByRole("form", { name: "Add phones" });
  fireEvent.click(within(form).getByLabelText("A new model"));
  fireEvent.change(within(form).getByLabelText("Phone model"), { target: { value: "x30" } });
  expect(within(form).getByText(/X30 is already in your list/)).toBeInTheDocument();
  expect(within(form).getByRole("button", { name: "Add phone" })).toBeDisabled();
});

it("an employee sees the plans but no commission", async () => {
  const strip = (phone) => ({ ...phone, plans: phone.plans.map((p) => { const rest = { ...p }; delete rest.commission; return rest; }) });
  api.mockImplementation(async () => ({ ...owner, phones: owner.phones.map(strip), can_see_money: false, can_set_up: false, can_undo: false,
    can_record_commission: undefined, summary: undefined, commissions: undefined }));
  render(<MkopaPage />);
  await screen.findByRole("heading", { name: "X30" });
  expect(screen.queryByText(/commission/i, { selector: "th" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "What would I earn?" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add phones" })).not.toBeInTheDocument();
});

it("reads a server error nested by position as words, never [object Object]", async () => {
  const { errorText } = await vi.importActual("../../core/api/client");
  expect(errorText({ enabled_modules: { 4: ['"mkopa" is not a valid choice.'] } })).toBe('"mkopa" is not a valid choice.');
});

const payingData = () => {
  const [cheap, quick] = owner.phones[0].plans;
  const unknownPlan = plan(31, 2999, 60, 365, null);
  const unpaid = [sale(1, "X30", cheap, "Mary Achieng", "2026-01-05"), sale(2, "X30", quick, "John Kamau", "2026-01-06"), sale(3, "X4", unknownPlan, "Ann Wairimu", "2026-01-07")];
  return { ...owner, unpaid, sales: unpaid };
};
const posted = () => JSON.parse(api.mock.calls.find(([path, o]) => path === "/api/v1/mkopa/commission/" && o?.method === "POST")[1].body);

it("records what M-KOPA paid for each phone specifically, the total adding itself up", async () => {
  api.mockImplementation(async (path, options) => (options?.method ? {} : payingData()));
  render(<MkopaPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Commission M-KOPA paid" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  expect(within(form).getByLabelText("An amount for each phone")).toBeChecked();
  expect(within(form).getByLabelText(/paid for the X30 sold to Mary Achieng/)).toHaveValue(1200);  // filled in with what is expected
  fireEvent.click(within(form).getByLabelText(/Ann Wairimu/, { selector: "input[type=checkbox]" }));
  fireEvent.change(within(form).getByLabelText(/paid for the X30 sold to John Kamau/), { target: { value: "1450" } });
  expect(within(form).getByText("Total M-KOPA paid").nextSibling).toHaveTextContent("KSh 2,650");
  fireEvent.click(within(form).getByRole("button", { name: "Record commission" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/mkopa/commission/", expect.objectContaining({ method: "POST" })));
  expect(posted()).toMatchObject({ method: "MPESA", amounts: [{ sale: 1, amount: "1200" }, { sale: 2, amount: "1450" }] });
  expect(posted().amount).toBeUndefined();
});

it("records one phone's commission straight from its row in Phones sold", async () => {
  api.mockImplementation(async (path, options) => (options?.method ? {} : payingData()));
  window.scrollTo = vi.fn();
  render(<MkopaPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Record commission for the X4 sold to Ann Wairimu" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  expect(within(form).getAllByRole("checkbox").map((box) => box.checked)).toEqual([false, false, true]);
  fireEvent.change(within(form).getByLabelText(/paid for the X4 sold to Ann Wairimu/), { target: { value: "900" } });
  fireEvent.click(within(form).getByRole("button", { name: "Record commission" }));
  await waitFor(() => expect(posted()).toMatchObject({ amounts: [{ sale: 3, amount: "900" }] }));
});

it("still takes one total for several phones when M-KOPA's statement gives only a total", async () => {
  api.mockImplementation(async (path, options) => (options?.method ? {} : payingData()));
  render(<MkopaPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Commission M-KOPA paid" }));
  const form = screen.getByRole("form", { name: "Record commission" });
  fireEvent.click(within(form).getByLabelText("One total for several phones"));
  fireEvent.click(within(form).getByLabelText(/Ann Wairimu/, { selector: "input[type=checkbox]" }));
  fireEvent.change(within(form).getByLabelText(/Total M-KOPA paid/), { target: { value: "2700" } });
  expect(within(form).getByRole("status")).toHaveTextContent(/expected KSh 2,700 for 2 phones/);
  fireEvent.click(within(form).getByRole("button", { name: "Record commission" }));
  await waitFor(() => expect(posted()).toMatchObject({ amount: "2700", sales: [1, 2] }));
});
