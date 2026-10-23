import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { POLL_INTERVAL, SubscriptionPage } from "./SubscriptionPage";
import { SubscriptionBanner } from "./SubscriptionBanner";
import { BusinessKinds, PlatformAdminPage } from "./PlatformAdminPage";
import { api } from "../../core/api/client";
import { askForm, confirmAction, showError, showSuccess } from "../../core/ui/alerts";
import { useAuth } from "../../core/auth/AuthContext";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ askForm: vi.fn(async () => null), confirmAction: vi.fn(async () => true), showError: vi.fn(async () => {}), showSuccess: vi.fn(async () => {}) }));
vi.mock("sweetalert2", () => ({ default: { fire: vi.fn(async () => ({})), close: vi.fn(), showLoading: vi.fn() } }));

const refresh = vi.fn(async () => {});
const PLANS = [
  { code: "BASIC", name: "Basic", price: "500.00", currency: "KES", period_days: 30, description: "Basics", features: ["Point of sale & receipts"], enabled_modules: ["pos"] },
  { code: "PRO", name: "Pro", price: "1000.00", currency: "KES", period_days: 30, description: "Everything", features: ["Profit & loss, balance sheet and reports"], enabled_modules: ["pos", "reports"] },
];
const trial = { status: "TRIAL", plan: "BASIC", plan_name: "Basic", ended: false, days_left: 23, ends_at: "2026-10-25T09:00:00Z", complimentary: false, expiring_soon: false };
beforeEach(() => {
  vi.clearAllMocks();
  POLL_INTERVAL.ms = 0;
  useAuth.mockReturnValue({ user: { roles: ["OWNER"], platform_admin: false, organization: { subscription: trial } }, refresh });
});

it("upgrades to Pro: confirms, sends the M-Pesa prompt, waits for the phone and reports success", async () => {
  let polls = 0;
  api.mockImplementation(async (path, options = {}) => {
    if (path === "/api/v1/tenancy/billing/") return { subscription: trial, plans: PLANS, payments: [], payment_methods: ["MPESA"], phone: "0712345678" };
    if (path === "/api/v1/tenancy/billing/pay/") return { id: 5, status: "PENDING", ...JSON.parse(options.body) };
    if (path === "/api/v1/tenancy/billing/payments/5/") return (polls += 1) < 2 ? { id: 5, status: "PENDING" }
      : { id: 5, status: "PAID", amount: "1000.00", currency: "KES", receipt_number: "QKJ1ABC23D", period_ends_at: "2026-11-24T09:00:00Z" };
    return {};
  });
  render(<MemoryRouter><SubscriptionPage /></MemoryRouter>);
  expect(await screen.findByText("Basic · Free month")).toBeInTheDocument();
  expect(screen.getByText(/^23 days left · until/)).toBeInTheDocument();
  expect(screen.getByLabelText(/M-Pesa number/)).toHaveValue("0712345678");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Upgrade · KES 1,000/ })); });
  await waitFor(() => expect(showSuccess).toHaveBeenCalled());
  expect(confirmAction.mock.calls[0][0]).toMatchObject({ title: "Switch to Pro for KES 1,000?", confirmButtonText: "Send M-Pesa prompt" });
  expect(confirmAction.mock.calls[0][0].text).toContain("0712345678");
  expect(JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/tenancy/billing/pay/")[1].body)).toEqual({ plan: "PRO", phone: "0712345678", method: "MPESA" });
  expect(showSuccess.mock.calls[0][1]).toContain("QKJ1ABC23D");
  expect(refresh).toHaveBeenCalled();
});

it("says which tools switch off when moving from Pro to Basic, and that nothing recorded is deleted", async () => {
  const named = [{ ...PLANS[0], feature_names: { pos: "Point of sale & receipts" } },
    { ...PLANS[1], feature_names: { pos: "Point of sale & receipts", reports: "Profit & loss, balance sheet and reports" } }];
  useAuth.mockReturnValue({ user: { roles: ["OWNER"], platform_admin: false, organization: { subscription: { ...trial, status: "ACTIVE", plan: "PRO", plan_name: "Pro" } } }, refresh });
  confirmAction.mockResolvedValueOnce(false);
  api.mockImplementation(async (path) => (path === "/api/v1/tenancy/billing/"
    ? { subscription: { ...trial, status: "ACTIVE", plan: "PRO", plan_name: "Pro" }, plans: named, payments: [], payment_methods: ["MPESA"], phone: "0712345678" } : {}));
  render(<MemoryRouter><SubscriptionPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Switch · KES 500/ }));
  await waitFor(() => expect(confirmAction).toHaveBeenCalled());
  expect(confirmAction.mock.calls[0][0].text).toContain("these switch off until you are back on Pro; nothing recorded in them is deleted: Profit & loss, balance sheet and reports");
  expect(api).not.toHaveBeenCalledWith("/api/v1/tenancy/billing/pay/", expect.anything());
});

it("does nothing when the owner cancels, and explains when M-Pesa is not set up", async () => {
  api.mockResolvedValue({ subscription: trial, plans: PLANS, payments: [], payment_methods: [], phone: "" });
  render(<MemoryRouter><SubscriptionPage /></MemoryRouter>);
  expect(await screen.findByText(/M-Pesa payments are not set up/)).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Upgrade/ })); });
  expect(showError).toHaveBeenCalledWith("Payments are not available yet", expect.any(String));
  expect(api.mock.calls.some(([path]) => path === "/api/v1/tenancy/billing/pay/")).toBe(false);
});

it("counts down on every page and tells staff what an ended subscription means", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-02T08:59:58Z"));
  try {
    const { rerender } = render(<MemoryRouter><SubscriptionBanner organization={{ subscription: trial }} canManage /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("Free month on Basic: 23 days 00h 00m 02s left");
    expect(screen.getByRole("status")).toHaveTextContent("Upgrade to Pro");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.getByRole("timer")).toHaveTextContent("23 days 00h 00m 01s");
    expect(screen.getByRole("link", { name: "Upgrade to Pro" })).toHaveAttribute("href", "/admin/subscription");
    rerender(<MemoryRouter><SubscriptionBanner organization={{ subscription: { ...trial, plan: "PRO", plan_name: "Pro", status: "ACTIVE", days_left: 3, expiring_soon: true, ends_at: "2026-10-04T12:30:05Z" } }} canManage /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("Pro: 2 days 03h 30m 06s left");
    expect(screen.getByRole("status")).toHaveTextContent("Renew before it ends");
    rerender(<MemoryRouter><SubscriptionBanner organization={{ subscription: { ...trial, plan: "PRO", plan_name: "Pro", status: "ACTIVE" } }} canManage={false} /></MemoryRouter>);
    expect(screen.getByRole("timer")).toHaveTextContent("23 days 00h 00m 01s");
    rerender(<MemoryRouter><SubscriptionBanner organization={{ subscription: { ...trial, status: "EXPIRED", ended: true, days_left: 0 } }} canManage={false} /></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("accounting, stock receiving and other tools are paused");
    expect(screen.getByRole("alert")).toHaveTextContent("Ask the business owner to renew.");
    rerender(<MemoryRouter><SubscriptionBanner organization={{ subscription: { ...trial, complimentary: true } }} canManage /></MemoryRouter>);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

const overview = {
  summary: { businesses: 2, trial: 1, paying: 1, ended: 0, expiring_soon: 0, complimentary: 0, by_plan: { BASIC: 1, PRO: 1 },
    revenue_this_month: "1000.00", revenue_total: "1000.00", currency: "KES", mpesa_mode: "off", mpesa_ready: false },
  businesses: [
    { id: 1, name: "Fresh Cuts", business_type: "Barbershop", owner: { name: "Otieno", username: "otieno", email: "o@example.test", phone: "0711000000" },
      subscription: trial, total_paid: "0", created_at: "2026-09-25T09:00:00Z" },
    { id: 2, name: "Mama Wanjiru", business_type: "Mama mboga / kibanda", owner: { name: "Wanjiru", username: "wanjiru", email: "", phone: "0722000000" },
      subscription: { ...trial, status: "ACTIVE", plan: "PRO", plan_name: "Pro" }, total_paid: "1000.00", created_at: "2026-09-20T09:00:00Z" },
  ],
  recent_payments: [], plans: PLANS.map((plan, index) => ({ ...plan, id: index + 1, active: true })),
};

it("shows the platform owner every business and records a payment received outside the app", async () => {
  useAuth.mockReturnValue({ user: { platform_admin: true } });
  api.mockImplementation(async (path, options = {}) => {
    if (path === "/api/v1/tenancy/platform-admin/overview/") return overview;
    if (path === "/api/v1/tenancy/platform-admin/businesses/1/") return options.method ? {} : { ...overview.businesses[0], members: 1, payments: [] };
    return {};
  });
  render(<MemoryRouter><PlatformAdminPage /></MemoryRouter>);
  expect(await screen.findByText("Fresh Cuts")).toBeInTheDocument();
  expect(screen.getByText(/M-Pesa payments are switched off/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Plan"), { target: { value: "PRO" } });
  expect(screen.queryByText("Fresh Cuts")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Plan"), { target: { value: "all" } });
  fireEvent.change(screen.getByLabelText("Search"), { target: { value: "0711" } });
  expect(screen.queryByText("Mama Wanjiru")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Fresh Cuts" }));
  const detail = await screen.findByRole("article", { name: "Fresh Cuts subscription" });
  const record = within(detail).getByRole("button", { name: "Record payment" }).closest("form");
  fireEvent.change(within(record).getByLabelText("Amount"), { target: { value: "500" } });
  fireEvent.change(within(record).getByLabelText("Receipt / reference"), { target: { value: "QKX99" } });
  await act(async () => { fireEvent.submit(record); });
  await waitFor(() => expect(showSuccess).toHaveBeenCalled());
  const [, options] = api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/platform-admin/businesses/1/" && o?.method === "POST");
  expect(JSON.parse(options.body)).toEqual({ plan: "BASIC", amount: "500", receipt_number: "QKX99" });
});

it("prices a plan for each kind of business and gives one business its own price", async () => {
  useAuth.mockReturnValue({ user: { platform_admin: true } });
  const kinds = [{ id: "duka", label: "Duka / general shop", model: "GOODS", listed: true }, { id: "mama_mboga", label: "Mama mboga / kibanda", model: "GOODS", listed: true }];
  const plans = overview.plans.map((plan) => ({ ...plan, kind_prices: plan.code === "BASIC" ? { duka: "700.00" } : {}, business_prices: 0 }));
  const pricing = { billing_sector: "mama_mboga", billing_kind: "Mama mboga / kibanda", sector: "duka", kind: "Duka / general shop", kind_changed: true,
    plans: [{ plan: "BASIC", plan_name: "Basic", price: "250.00", source: "kind", kind_price: "250.00", currency: "KES", note: "" },
      { plan: "PRO", plan_name: "Pro", price: "1000.00", source: "standard", kind_price: "1000.00", currency: "KES", note: "" }] };
  api.mockImplementation(async (path, options = {}) => {
    if (path === "/api/v1/tenancy/platform-admin/overview/") return { ...overview, plans, kinds };
    if (path === "/api/v1/tenancy/platform-admin/businesses/2/") return options.method ? {} : { ...overview.businesses[1], members: 1, payments: [], pricing };
    return {};
  });
  render(<MemoryRouter><PlatformAdminPage /></MemoryRouter>);
  const basic = await screen.findByRole("form", { name: "Basic plan" });
  expect(within(basic).getByText(/Price for each kind of business \(1 set\)/)).toBeInTheDocument();
  expect(within(basic).getByLabelText("Duka / general shop")).toHaveValue(700);
  fireEvent.change(within(basic).getByLabelText("Mama mboga / kibanda"), { target: { value: "250" } });
  fireEvent.change(within(basic).getByLabelText("Duka / general shop"), { target: { value: "" } });
  await act(async () => { fireEvent.submit(basic); });
  const [, saved] = api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/platform-admin/plans/1/" && o?.method === "PATCH");
  expect(JSON.parse(saved.body).kind_prices).toEqual({ duka: null, mama_mboga: "250" });  // only what changed; emptied goes back to standard

  fireEvent.click(screen.getByRole("button", { name: "Mama Wanjiru" }));
  const detail = await screen.findByRole("article", { name: "Mama Wanjiru subscription" });
  expect(within(detail).getByText("Basic: KES 250")).toBeInTheDocument();
  expect(within(detail).getByText(/still billed as/)).toHaveTextContent("changed the kind of business to Duka / general shop, but it is still billed as Mama mboga / kibanda");
  expect(within(detail).getByLabelText("Amount")).toHaveValue(1000);  // a payment for its plan defaults to what it pays
  const own = within(detail).getByRole("button", { name: "Save its own prices" }).closest("form");
  fireEvent.change(within(own).getByLabelText(/Own price for Basic/), { target: { value: "300" } });
  await act(async () => { fireEvent.submit(own); });
  const [, priced] = api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/platform-admin/businesses/2/" && o?.method === "PATCH");
  expect(JSON.parse(priced.body)).toEqual({ prices: { BASIC: "300" }, note: "" });
});

it("deletes a switched-off business only with its name and the administrator's protected pages password", async () => {
  useAuth.mockReturnValue({ user: { platform_admin: true } });
  let status = { has_password: false, expired: false, lifetime_days: 7, shortest: 6 };
  api.mockImplementation(async (path, options = {}) => {
    if (path === "/api/v1/tenancy/platform-admin/overview/") return overview;
    if (path === "/api/v1/tenancy/platform-admin/businesses/1/") return options.method ? { deleted: "Fresh Cuts", records: 9 } : { ...overview.businesses[0], active: false, members: 1, payments: [] };
    if (path === "/api/v1/auth/protected/") return { protected: status };
    if (path === "/api/v1/auth/protected/password/") { status = { ...status, has_password: true }; return { protected: status }; }
    return {};
  });
  askForm.mockResolvedValue({ confirm_name: "Fresh Cuts", password: "pages-pass" });
  render(<MemoryRouter><PlatformAdminPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Fresh Cuts" }));
  const detail = await screen.findByRole("article", { name: "Fresh Cuts subscription" });
  // No protected pages password yet: it is set first, then the delete is asked for.
  fireEvent.click(within(detail).getByRole("button", { name: "Delete business for good" }));
  expect(await within(detail).findByRole("heading", { name: "Set a password for protected pages" })).toBeInTheDocument();
  expect(askForm).not.toHaveBeenCalled();
  fireEvent.change(within(detail).getByLabelText("Your sign-in password"), { target: { value: "Sign-in-1" } });
  fireEvent.change(within(detail).getByLabelText("New protected pages password"), { target: { value: "pages-pass" } });
  fireEvent.change(within(detail).getByLabelText("New password again"), { target: { value: "pages-pass" } });
  await act(async () => { fireEvent.click(within(detail).getByRole("button", { name: "Save and open" })); });
  await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Business deleted", expect.any(String)));
  expect(askForm.mock.calls[0][0].fields.map((f) => [f.name, f.type])).toEqual([["confirm_name", undefined], ["password", "password"]]);
  const [, options] = api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/platform-admin/businesses/1/" && o?.method === "DELETE");
  expect(JSON.parse(options.body)).toEqual({ confirm_name: "Fresh Cuts", password: "pages-pass" });
});

it("keeps the platform page away from everyone else", () => {
  useAuth.mockReturnValue({ user: { platform_admin: false } });
  render(<MemoryRouter><PlatformAdminPage /></MemoryRouter>);
  expect(api).not.toHaveBeenCalled();
});

it("lets the platform owner tidy and list a kind of business an owner added", async () => {
  const kind = { id: 4, sector_id: "kind-4", business_model: "GOODS", label: "Poultry farm", hint: "", keywords: "", modules: ["inventory", "pos"],
    categories: ["Eggs"], services: [], status: "SUGGESTED", uses: 3, created_by: "Kuku Bora", created_at: "2026-10-12T08:00:00Z",
    allowed_modules: ["inventory", "locations", "pos", "customers", "expenses", "mpesa", "reports", "branches", "staff", "chama"] };
  api.mockImplementation(async (path, options = {}) => (options.method ? { ...kind, status: "LISTED" } : [kind]));
  render(<BusinessKinds />);
  const form = await screen.findByRole("form", { name: "Poultry farm" });
  expect(within(form).getByText(/3 businesses · first added by Kuku Bora/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Short description"), { target: { value: "Eggs, broilers and layers" } });
  fireEvent.change(within(form).getByLabelText("Product categories"), { target: { value: "Eggs, Broilers ," } });
  fireEvent.click(within(form).getByLabelText(/Customers/));
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "List for everyone" })); });
  await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Listed", "New owners can now choose Poultry farm."));
  const [, options] = api.mock.calls.find(([, o]) => o?.method === "PATCH");
  expect(JSON.parse(options.body)).toEqual({ label: "Poultry farm", hint: "Eggs, broilers and layers", keywords: "",
    modules: ["inventory", "pos", "customers"], categories: ["Eggs", "Broilers"], status: "LISTED" });
});
