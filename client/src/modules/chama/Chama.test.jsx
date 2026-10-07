import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { BusinessSetupPage } from "../platform/BusinessSetup";
import profiles from "../platform/businessProfiles.fixture.json";
import { api } from "../../core/api/client";
import { askForm } from "../../core/ui/alerts";
import { emptyChama, chamaPayload, chamaProblem } from "./ChamaSetupFields";
import { ChamaDashboardCard } from "./ChamaDashboardCard";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", async (original) => ({ ...(await original()), askForm: vi.fn(), confirmAction: vi.fn(async () => true) }));
const refresh = vi.fn(async () => {});
const user = { id: 1, first_name: "Larry", last_name: "Musau", phone: "0712345678", memberships: [], permissions: ["chama.view_chama", "chama.add_chama"] };
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user, loading: false, refresh }) }));
const PLANS = { trial_days: 30, plans: [
  { code: "BASIC", name: "Basic", price: "500.00", currency: "KES", description: "Basics", enabled_modules: ["inventory", "services", "pos", "customers", "expenses", "mpesa"] },
  { code: "PRO", name: "Pro", price: "1000.00", currency: "KES", description: "Everything", enabled_modules: [...profiles.modules.map((m) => m.id)] }] };
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  api.mockImplementation(async (path) => (path === "/api/v1/tenancy/business-profiles/" ? profiles : path === "/api/v1/tenancy/plans/" ? PLANS
    : path === "/api/v1/tenancy/create/" ? { id: 9, name: "Created" } : {}));
});
const next = () => fireEvent.click(screen.getByRole("button", { name: "Continue" }));

it("checks a chama the way the server does", () => {
  const chama = emptyChama(user);
  expect(chama.members[0]).toMatchObject({ full_name: "Larry Musau", phone: "0712345678", role: "TREASURER" });
  expect(chamaProblem(chama)).toBe("Enter the chama's name.");
  const filled = { ...chama, name: "Umoja", contribution_amount: "500",
    members: [{ ...chama.members[0], id_number: "12345678" }, { full_name: "Mary Achieng", id_number: "23456789", phone: "0722 000 111", role: "MEMBER" },
      { full_name: "", id_number: "", phone: "", role: "MEMBER" }] };
  expect(chamaProblem(filled)).toBe("");
  expect(chamaPayload(filled).members).toHaveLength(2);  // the blank row is left out
  expect(chamaProblem({ ...filled, members: filled.members.map((m) => ({ ...m, role: "MEMBER" })) })).toBe("Choose the chama's treasurer.");
  expect(chamaProblem({ ...filled, members: [filled.members[0], { ...filled.members[1], id_number: "12345678" }] })).toBe("Two members have the same ID number.");
  expect(chamaProblem({ ...filled, members: [filled.members[0], { ...filled.members[1], full_name: "Mary" }] })).toMatch(/full name/);
});

it("adds a chama step to registration when chama management is chosen", async () => {
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Your business" });
  fireEvent.change(screen.getByLabelText("Business name"), { target: { value: "Mama Duka" } });
  fireEvent.click(screen.getByRole("button", { name: /I sell goods/ }));
  next();
  fireEvent.click(screen.getByRole("button", { name: /Duka \/ general shop/ }));
  next();
  expect(screen.queryByRole("heading", { name: "Your chama" })).not.toBeInTheDocument();
  const tool = screen.getByRole("button", { name: /^Chama management/ });
  expect(within(tool).getByText("Pro plan")).toBeInTheDocument();
  fireEvent.click(tool);
  next();

  expect(screen.getByRole("heading", { name: "Your chama" })).toBeInTheDocument();
  expect(screen.getByText(/kept completely apart from your shop/)).toBeInTheDocument();
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter the chama's name.");
  fireEvent.change(screen.getByLabelText("Chama name"), { target: { value: "Wamama Chama" } });
  fireEvent.change(screen.getByLabelText(/Each member contributes/), { target: { value: "300" } });
  fireEvent.change(screen.getByLabelText(/Fine for paying late/), { target: { value: "50" } });
  const ids = screen.getAllByLabelText("ID number");
  fireEvent.change(ids[0], { target: { value: "12345678" } });
  fireEvent.change(screen.getAllByLabelText("Full name")[1], { target: { value: "Mary Achieng" } });
  fireEvent.change(ids[1], { target: { value: "23456789" } });
  fireEvent.change(screen.getAllByLabelText("Phone")[1], { target: { value: "0722000111" } });
  // Making Mary treasurer moves the role from Larry.
  fireEvent.change(screen.getAllByLabelText("Role")[1], { target: { value: "TREASURER" } });
  expect(screen.getAllByLabelText("Role").map((select) => select.value)).toEqual(["MEMBER", "TREASURER"]);
  fireEvent.click(screen.getByRole("button", { name: "Move Mary Achieng up" }));
  expect(screen.getAllByLabelText("Full name").map((input) => input.value)).toEqual(["Mary Achieng", "Larry Musau"]);
  // Give 100 every day; after a week one member receives, and the members agree who.
  fireEvent.change(screen.getByLabelText("How often"), { target: { value: "DAILY" } });
  fireEvent.change(screen.getByLabelText(/Contributions in each turn/), { target: { value: "7" } });
  expect(screen.getByText(/7 means everyone gives every day for a week/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Members agree who receives next/ }));
  fireEvent.change(screen.getByLabelText(/Who receives the first turn/), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Move Larry Musau up" }));  // the choice follows Larry's row
  expect(screen.getByLabelText(/Who receives the first turn/)).toHaveValue("0");
  next();
  next();
  next();

  expect(screen.getByText(/Wamama Chama · KES 300 each · 2 members · treasurer Mary Achieng/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: /Pro · KES 1,000/ }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  const body = JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/tenancy/create/")[1].body);
  expect(body.enabled_modules).toContain("chama");
  expect(body.chama).toMatchObject({ name: "Wamama Chama", contribution_amount: "300", fine_amount: "50", payout_mode: "ROTATION",
    frequency: "DAILY", periods_per_round: 7, turn_choice: "AGREED", first_receiver: 0,
    members: [{ full_name: "Larry Musau", id_number: "12345678", role: "MEMBER" }, { full_name: "Mary Achieng", role: "TREASURER" }] });
}, 20000);  // a whole multi-step set-up: slow when every test file runs at once

it("offers the owner a chama on the dashboard, or shows each chama at a glance", async () => {
  api.mockImplementation(async (path) => (path === "/api/v1/chama/setup/" ? { enabled: false, plan_allows: true, can_manage: true, can_turn_on: true, chamas: 0 } : {}));
  const { unmount } = render(<MemoryRouter><ChamaDashboardCard /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Are you the treasurer of a chama?" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Set up a chama" })).toHaveAttribute("href", "/admin/chama/setup");
  unmount();
  api.mockImplementation(async (path) => (path === "/api/v1/chama/setup/" ? { enabled: true, plan_allows: true, can_manage: true, can_turn_on: true, chamas: 1 }
    : path === "/api/v1/chama/" ? { chamas: [{ id: 3, name: "Umoja", contribution_amount: "500", frequency: "WEEKLY", members: 3, held: "1000",
      current_period: "2026-10-06", next_period: "2026-10-13", paid_count: 2, due_count: 3, late_count: 1, collected: "1000", expected: "1500",
      next_turn: { member: "Mary Achieng", date: "2026-10-06", round: 1 } }] } : {}));
  render(<MemoryRouter><ChamaDashboardCard /></MemoryRouter>);
  const card = await screen.findByRole("link", { name: /Umoja/ });
  expect(card).toHaveAttribute("href", "/admin/chama/3");
  expect(card).toHaveTextContent("2 of 3 paid");
  expect(card).toHaveTextContent("1 late");
  expect(card).toHaveTextContent("Next turn: Mary Achieng");
  expect(screen.getByText(/not included in any of the shop's figures/)).toBeInTheDocument();
});

const member = (id, full_name, role, extra = {}) => ({ id, full_name, id_number: `2000000${id}`, phone: `07120000${id}`, role, role_label: role === "TREASURER" ? "Treasurer" : "Member",
  turn_position: id, joined_on: "2026-10-06", left_on: null, leave_reason: "", active: true, unpaid: "0", late: "0", fines_owed: "0", paid_in: "0", received: "0",
  next_turn: null, this_period: null, ...extra });
const due = (status, paid, extra = {}) => ({ id: 50 + paid, member_id: 1, period_date: "2026-10-06", amount: "500", paid: String(paid), deadline: "2026-10-08", pay_by: "2026-10-08",
  status, excused_until: null, excuse_reason: "", fine_amount: "0", fine_paid: "0", fine_owed: "0", fined_on: null, fine_waived: false, fine_waive_reason: "", ...extra });
const DETAIL = {
  id: 3, name: "Umoja", contribution_amount: "500", frequency: "WEEKLY", start_date: "2026-10-06", grace_days: 2, fine_amount: "50", payout_mode: "ROTATION",
  periods_per_round: 1, notes: "", today: "2026-10-09", turn_choice: "AGREED", next_receiver: null,
  still_to_receive: [{ id: 1, full_name: "Larry Musau" }, { id: 2, full_name: "Mary Achieng" }, { id: 3, full_name: "John Kamau" }], schedule_locked: true, turns_locked: false, current_period: "2026-10-06", next_period: "2026-10-13", current_round: 1,
  money: { held: "500", paid_in: "500", fines_paid: "0", given_out: "0", unpaid: "1000", late: "1000", fines_owed: "100" },
  members: [member(1, "Larry Musau", "TREASURER", { paid_in: "500", this_period: due("PAID", 500), next_turn: { round: 1, date: "2026-10-06" } }),
    member(2, "Mary Achieng", "MEMBER", { unpaid: "500", late: "500", fines_owed: "50", this_period: due("LATE", 0, { member_id: 2, fine_amount: "50", fine_owed: "50" }) }),
    member(3, "John Kamau", "MEMBER", { unpaid: "500", this_period: due("EXCUSED", 0, { member_id: 3, excused_until: "2026-10-20", excuse_reason: "Salary" }) })],
  turns: [{ round: 1, date: "2026-10-06", member_id: null, member: "", agreed: false, expected: "1500", collected: "500", status: "DUE" },
    { round: 2, date: "2026-10-13", member_id: null, member: "", agreed: false, expected: "1500", collected: "0", status: "UPCOMING" }],
  fines: [{ ...due("LATE", 0, { member_id: 2, fine_amount: "50", fine_owed: "50" }), member: "Mary Achieng" }],
  excuses: [{ ...due("EXCUSED", 0, { member_id: 3, excused_until: "2026-10-20", excuse_reason: "Salary" }), member: "John Kamau" }],
  payments: [{ id: 7, member_id: 1, member: "Larry Musau", amount: "500", paid_on: "2026-10-06", method: "MPESA", reference: "SK1", recorded_by: "Larry",
    reversed_at: null, reverse_reason: "", allocations: [{ period_date: "2026-10-06", part: "CONTRIBUTION", amount: "500" }] }],
  payouts: [],
};

it("shows who has paid, fines, excuses and whose turn it is", async () => {
  const { ChamaDetailPage } = await import("./ChamaPages");
  const { Route, Routes } = await import("react-router-dom");
  user.permissions = ["chama.view_chama", "chama.change_chama", "chama.add_chamapayment", "chama.add_chamapayout"];
  api.mockImplementation(async (path) => (path === "/api/v1/chama/3/" ? DETAIL : {}));
  render(<MemoryRouter initialEntries={["/admin/chama/3"]}><Routes><Route path="/admin/chama/:id" element={<ChamaDetailPage />} /></Routes></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Umoja" })).toBeInTheDocument();
  expect(screen.getByText(/kept apart from the shop's money/)).toBeInTheDocument();
  expect(screen.getByText("1 of 3 members have paid this week. The next contribution is on", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("Late")).toBeInTheDocument();
  expect(screen.getByText(/Excused until/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Record payment" })[1]);
  expect(screen.getByRole("form", { name: "Payment from Mary Achieng" })).toBeInTheDocument();
  expect(screen.getByLabelText(/Amount/)).toHaveValue(550);  // contribution and fine owed
  expect(screen.getByText("not agreed yet")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Turns" }));
  expect(screen.getByText(/Not agreed yet. Record the member/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /their money/ })).not.toBeInTheDocument();  // not until the members agree
  expect(screen.getByText(/collected KSh 500 of KSh 1,500/)).toBeInTheDocument();
  api.mockImplementation(async (path) => (path === "/api/v1/chama/3/next-receiver/" ? { ...DETAIL,
    next_receiver: { id: 2, full_name: "Mary Achieng", note: "Agreed on Sunday" },
    turns: [{ ...DETAIL.turns[0], member_id: 2, member: "Mary Achieng", agreed: true }, DETAIL.turns[1]] } : DETAIL));
  fireEvent.click(screen.getByRole("button", { name: "Record who the members agreed" }));
  fireEvent.change(screen.getByLabelText("The members agreed"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText(/Note/), { target: { value: "Agreed on Sunday" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save who receives next" })); });
  expect(JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/chama/3/next-receiver/")[1].body)).toEqual({ member: "2", note: "Agreed on Sunday" });
  expect(screen.getByRole("button", { name: "Give Mary Achieng their money" })).toBeInTheDocument();
  expect(screen.getAllByText("To be agreed")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Fines & excuses" }));
  expect(screen.getByRole("button", { name: "Waive" })).toBeInTheDocument();
  expect(screen.getByText("Salary")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Members" }));
  expect(screen.getByText("20000002")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Money record" }));
  expect(screen.getByText("M-Pesa · SK1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Rules" }));
  expect(screen.getByLabelText("How often")).toBeDisabled();
});


it("removes a member who left or was added by mistake, and lets a member rejoin", async () => {
  const { ChamaDetailPage } = await import("./ChamaPages");
  const { Route, Routes } = await import("react-router-dom");
  user.permissions = ["chama.view_chama", "chama.change_chama"];
  const detail = { ...DETAIL, members: [DETAIL.members[0], { ...DETAIL.members[1], has_money_history: true }, { ...DETAIL.members[2], has_money_history: false },
    member(4, "Peter Otieno", "MEMBER", { active: false, left_on: "2026-10-08", has_money_history: false })] };
  api.mockImplementation(async () => detail);
  render(<MemoryRouter initialEntries={["/admin/chama/3"]}><Routes><Route path="/admin/chama/:id" element={<ChamaDetailPage />} /></Routes></MemoryRouter>);
  await screen.findByRole("heading", { name: "Umoja" });
  fireEvent.click(screen.getByRole("button", { name: "Members" }));
  const row = (name) => screen.getByRole("row", { name: new RegExp(name) });
  expect(within(row("Larry Musau")).getByRole("button", { name: /^Remove/ })).toBeDisabled();  // the treasurer
  // No money history: the owner may delete a member added by mistake.
  askForm.mockResolvedValueOnce({ how: "MISTAKE", reason: "Wrong chama" });
  await act(async () => { fireEvent.click(within(row("John Kamau")).getByRole("button", { name: /^Remove/ })); });
  expect(askForm.mock.calls[0][0].fields.map((f) => f.name)).toEqual(["how", "reason"]);
  expect(api).toHaveBeenCalledWith("/api/v1/chama/3/members/3/remove/", expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Wrong chama" }) }));
  // With payments on record, the only way out is leaving.
  askForm.mockResolvedValueOnce({ reason: "Moved away" });
  await act(async () => { fireEvent.click(within(row("Mary Achieng")).getByRole("button", { name: /^Remove/ })); });
  expect(askForm.mock.calls[1][0].fields.map((f) => f.name)).toEqual(["reason"]);
  expect(api).toHaveBeenCalledWith("/api/v1/chama/3/members/2/leave/", expect.objectContaining({ body: JSON.stringify({ reason: "Moved away" }) }));
  await act(async () => { fireEvent.click(within(row("Peter Otieno")).getByRole("button", { name: "Rejoins" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/chama/3/members/4/rejoin/", expect.objectContaining({ method: "POST" }));
});
