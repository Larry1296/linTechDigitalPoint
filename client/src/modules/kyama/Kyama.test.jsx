import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { BusinessSetupPage } from "../platform/BusinessSetup";
import profiles from "../platform/businessProfiles.fixture.json";
import { api } from "../../core/api/client";
import { emptyKyama, kyamaPayload, kyamaProblem } from "./KyamaSetupFields";
import { KyamaDashboardCard } from "./KyamaDashboardCard";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
const refresh = vi.fn(async () => {});
const user = { id: 1, first_name: "Larry", last_name: "Musau", phone: "0712345678", memberships: [], permissions: ["kyama.view_kyama", "kyama.add_kyama"] };
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

it("checks a kyama the way the server does", () => {
  const kyama = emptyKyama(user);
  expect(kyama.members[0]).toMatchObject({ full_name: "Larry Musau", phone: "0712345678", role: "TREASURER" });
  expect(kyamaProblem(kyama)).toBe("Enter the kyama's name.");
  const filled = { ...kyama, name: "Umoja", contribution_amount: "500",
    members: [{ ...kyama.members[0], id_number: "12345678" }, { full_name: "Mary Achieng", id_number: "23456789", phone: "0722 000 111", role: "MEMBER" },
      { full_name: "", id_number: "", phone: "", role: "MEMBER" }] };
  expect(kyamaProblem(filled)).toBe("");
  expect(kyamaPayload(filled).members).toHaveLength(2);  // the blank row is left out
  expect(kyamaProblem({ ...filled, members: filled.members.map((m) => ({ ...m, role: "MEMBER" })) })).toBe("Choose the kyama's treasurer.");
  expect(kyamaProblem({ ...filled, members: [filled.members[0], { ...filled.members[1], id_number: "12345678" }] })).toBe("Two members have the same ID number.");
  expect(kyamaProblem({ ...filled, members: [filled.members[0], { ...filled.members[1], full_name: "Mary" }] })).toMatch(/full name/);
});

it("adds a kyama step to registration when kyama management is chosen", async () => {
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Your business" });
  fireEvent.change(screen.getByLabelText("Business name"), { target: { value: "Mama Duka" } });
  fireEvent.click(screen.getByRole("button", { name: /I sell goods/ }));
  next();
  fireEvent.click(screen.getByRole("button", { name: /Duka \/ general shop/ }));
  next();
  expect(screen.queryByRole("heading", { name: "Your kyama" })).not.toBeInTheDocument();
  const tool = screen.getByRole("button", { name: /^Kyama \(chama\) management/ });
  expect(within(tool).getByText("Pro plan")).toBeInTheDocument();
  fireEvent.click(tool);
  next();

  expect(screen.getByRole("heading", { name: "Your kyama" })).toBeInTheDocument();
  expect(screen.getByText(/kept completely apart from your shop/)).toBeInTheDocument();
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter the kyama's name.");
  fireEvent.change(screen.getByLabelText("Kyama name"), { target: { value: "Wamama Chama" } });
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
  next();
  next();
  next();

  expect(screen.getByText(/Wamama Chama · KES 300 each · 2 members · treasurer Mary Achieng/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: /Pro · KES 1,000/ }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  const body = JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/tenancy/create/")[1].body);
  expect(body.enabled_modules).toContain("kyama");
  expect(body.kyama).toMatchObject({ name: "Wamama Chama", contribution_amount: "300", fine_amount: "50", frequency: "WEEKLY", payout_mode: "ROTATION",
    members: [{ full_name: "Mary Achieng", role: "TREASURER" }, { full_name: "Larry Musau", id_number: "12345678", role: "MEMBER" }] });
}, 20000);  // a whole multi-step set-up: slow when every test file runs at once

it("offers the owner a kyama on the dashboard, or shows each kyama at a glance", async () => {
  api.mockImplementation(async (path) => (path === "/api/v1/kyama/setup/" ? { enabled: false, plan_allows: true, can_manage: true, can_turn_on: true, kyamas: 0 } : {}));
  const { unmount } = render(<MemoryRouter><KyamaDashboardCard /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Are you the treasurer of a kyama?" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Set up a kyama" })).toHaveAttribute("href", "/admin/kyama/setup");
  unmount();
  api.mockImplementation(async (path) => (path === "/api/v1/kyama/setup/" ? { enabled: true, plan_allows: true, can_manage: true, can_turn_on: true, kyamas: 1 }
    : path === "/api/v1/kyama/" ? { kyamas: [{ id: 3, name: "Umoja", contribution_amount: "500", frequency: "WEEKLY", members: 3, held: "1000",
      current_period: "2026-10-06", next_period: "2026-10-13", paid_count: 2, due_count: 3, late_count: 1, collected: "1000", expected: "1500",
      next_turn: { member: "Mary Achieng", date: "2026-10-06", round: 1 } }] } : {}));
  render(<MemoryRouter><KyamaDashboardCard /></MemoryRouter>);
  const card = await screen.findByRole("link", { name: /Umoja/ });
  expect(card).toHaveAttribute("href", "/admin/kyama/3");
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
  periods_per_round: 1, notes: "", today: "2026-10-09", schedule_locked: true, turns_locked: false, current_period: "2026-10-06", next_period: "2026-10-13", current_round: 1,
  money: { held: "500", paid_in: "500", fines_paid: "0", given_out: "0", unpaid: "1000", late: "1000", fines_owed: "100" },
  members: [member(1, "Larry Musau", "TREASURER", { paid_in: "500", this_period: due("PAID", 500), next_turn: { round: 1, date: "2026-10-06" } }),
    member(2, "Mary Achieng", "MEMBER", { unpaid: "500", late: "500", fines_owed: "50", this_period: due("LATE", 0, { member_id: 2, fine_amount: "50", fine_owed: "50" }) }),
    member(3, "John Kamau", "MEMBER", { unpaid: "500", this_period: due("EXCUSED", 0, { member_id: 3, excused_until: "2026-10-20", excuse_reason: "Salary" }) })],
  turns: [{ round: 1, date: "2026-10-06", member_id: 1, member: "Larry Musau", expected: "1500", collected: "500", status: "DUE" },
    { round: 2, date: "2026-10-13", member_id: 2, member: "Mary Achieng", expected: "1500", collected: "0", status: "UPCOMING" }],
  fines: [{ ...due("LATE", 0, { member_id: 2, fine_amount: "50", fine_owed: "50" }), member: "Mary Achieng" }],
  excuses: [{ ...due("EXCUSED", 0, { member_id: 3, excused_until: "2026-10-20", excuse_reason: "Salary" }), member: "John Kamau" }],
  payments: [{ id: 7, member_id: 1, member: "Larry Musau", amount: "500", paid_on: "2026-10-06", method: "MPESA", reference: "SK1", recorded_by: "Larry",
    reversed_at: null, reverse_reason: "", allocations: [{ period_date: "2026-10-06", part: "CONTRIBUTION", amount: "500" }] }],
  payouts: [],
};

it("shows who has paid, fines, excuses and whose turn it is", async () => {
  const { KyamaDetailPage } = await import("./KyamaPages");
  const { Route, Routes } = await import("react-router-dom");
  user.permissions = ["kyama.view_kyama", "kyama.change_kyama", "kyama.add_kyamapayment", "kyama.add_kyamapayout"];
  api.mockImplementation(async (path) => (path === "/api/v1/kyama/3/" ? DETAIL : {}));
  render(<MemoryRouter initialEntries={["/admin/kyama/3"]}><Routes><Route path="/admin/kyama/:id" element={<KyamaDetailPage />} /></Routes></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Umoja" })).toBeInTheDocument();
  expect(screen.getByText(/kept apart from the shop's money/)).toBeInTheDocument();
  expect(screen.getByText("1 of 3 members have paid this week. The next contribution is on", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("Late")).toBeInTheDocument();
  expect(screen.getByText(/Excused until/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Record payment" })[1]);
  expect(screen.getByRole("form", { name: "Payment from Mary Achieng" })).toBeInTheDocument();
  expect(screen.getByLabelText(/Amount/)).toHaveValue(550);  // contribution and fine owed
  fireEvent.click(screen.getByRole("button", { name: "Turns" }));
  expect(screen.getByRole("button", { name: "Give Larry Musau their money" })).toBeInTheDocument();
  expect(screen.getByText(/collected KSh 500 of KSh 1,500/)).toBeInTheDocument();
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
