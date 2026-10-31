import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import profiles from "../platform/businessProfiles.fixture.json";
import { SettingsPage } from "./SettingsPage";
import { api } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true), askForm: vi.fn(async () => ({ password: "Sign-in-1" })) }));

const settings = { name: "Alpha", business_type: "Duka / general shop", business_model: "GOODS", sector: "duka", business_size: "SMALL", phone: "", email: "", address: "", currency: "KES", timezone: "Africa/Nairobi",
  country: "KE", enabled_modules: ["inventory", "pos"], available_modules: ["inventory", "pos", "mpesa"], receipt_footer: "" };
const staff = { roles: ["EMPLOYEE", "ADMIN", "MANAGER", "CASHIER"], staff: [
  { id: 1, username: "owner", email: "", name: "", role: "OWNER", status: "ACTIVE", page_pins: [] },
  { id: 2, username: "jane", email: "", name: "Jane", role: "CASHIER", status: "ACTIVE", hidden_pages: ["loans"], page_pins: [] },
  { id: 4, username: "kim", email: "", name: "Kim", role: "EMPLOYEE", status: "ACTIVE", open_pages: ["sales"], setup_pending: false, lock_pin_set: true, page_pins: ["mpesa"] },
], pages: [{ key: "sales", label: "Selling" }, { key: "mpesa", label: "M-Pesa agency" }, { key: "loans", label: "Money lent" }],
  work_pages: [{ key: "sales", label: "Selling" }, { key: "mpesa", label: "M-Pesa agency" }] };

let pins;
function pinState(options) {
  if (options.method === "POST") {
    const { page, pin } = JSON.parse(options.body);
    if (page) pins.pages[page] = { ...pins.pages[page], set: true, length: pin.length };
    else pins.pin = { set: true, length: pin.length };
  }
  return structuredClone(pins);
}

beforeEach(() => {
  vi.clearAllMocks();
  // A cashier: the owner has set the M-Pesa PIN; Investments, the owner's alone, is not listed for them.
  pins = { pin: { set: false, length: null }, is_owner: false, pages: { mpesa: { label: "M-Pesa", set: true, length: 4, can_set: false } } };
  api.mockImplementation(async (path, options = {}) => {
    if (path === "/api/v1/tenancy/business-profiles/") return profiles;
    if (path === "/api/v1/tenancy/settings/") return options.method === "PATCH" ? { ...settings, ...JSON.parse(options.body) } : settings;
    if (path === "/api/v1/tenancy/branches/") return options.method === "POST" ? { id: 3, ...JSON.parse(options.body) } : [
      { id: 1, name: "Main branch", address: "", phone: "", email: "", is_active: true, is_main: true },
      { id: 2, name: "Old stall", address: "Kiandas", phone: "", email: "", is_active: false, is_main: false }];
    if (path === "/api/v1/tenancy/staff/") return options.method === "POST" ? { id: 3, username: "sam" } : staff;
    if (path === "/api/v1/auth/lock-pin/") return pinState(options);
    return {};
  });
});

const renderAs = (role) => {
  useAuth.mockReturnValue({ user: { roles: [role], permissions: [] }, refresh: vi.fn() });
  return render(<MemoryRouter><SettingsPage /></MemoryRouter>);
};

it("lets the owner save business details and add an employee with the pages they can open", async () => {
  renderAs("OWNER");
  const business = (await screen.findByRole("heading", { name: "Business details" })).closest("form");
  fireEvent.change(within(business).getByLabelText("Business name"), { target: { value: "Alpha Traders" } });
  fireEvent.click(within(business).getByLabelText("M-Pesa agency"));
  fireEvent.click(within(business).getByRole("button", { name: "Save business details" }));
  await screen.findByText("Business settings saved.");
  const saved = JSON.parse(api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/settings/" && o?.method === "PATCH")[1].body);
  expect(saved).toMatchObject({ name: "Alpha Traders", business_model: "GOODS", sector: "duka", enabled_modules: ["inventory", "pos", "mpesa"] });

  const staffForm = screen.getByRole("heading", { name: "Add an employee" }).closest("form");
  expect(screen.queryByRole("combobox", { name: "Account for owner" })).toBeNull();
  fireEvent.change(within(staffForm).getByLabelText(/^Username/), { target: { value: "sam" } });
  fireEvent.change(within(staffForm).getByLabelText(/^Temporary password/), { target: { value: "Strong-pass-2026" } });
  fireEvent.click(within(staffForm).getByLabelText("They can open M-Pesa agency"));
  fireEvent.click(within(staffForm).getByRole("button", { name: "Add employee" }));
  await screen.findByText(/Added sam/);
  const added = JSON.parse(api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/staff/" && o?.method === "POST")[1].body);
  expect(added).toMatchObject({ username: "sam", role: "EMPLOYEE", password: "Strong-pass-2026", open_pages: ["mpesa"], email: "" });
});

it("lets the owner change a role and suspend a staff member", async () => {
  renderAs("OWNER");
  fireEvent.change(await screen.findByRole("combobox", { name: "Account for jane" }), { target: { value: "MANAGER" } });
  fireEvent.click(within(screen.getByText("jane").closest("tr")).getByRole("button", { name: "Suspend" }));
  await waitFor(() => expect(api.mock.calls.filter(([path]) => path === "/api/v1/tenancy/staff/2/")).toHaveLength(2));
  const bodies = api.mock.calls.filter(([path]) => path === "/api/v1/tenancy/staff/2/").map(([, o]) => JSON.parse(o.body));
  expect(bodies).toEqual([{ role: "MANAGER" }, { status: "SUSPENDED" }]);
});

it("shows only the PIN and password forms to other staff", async () => {
  renderAs("CASHIER");
  expect(screen.getByRole("heading", { name: "Change your password" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "Lock PIN and private pages" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Business details" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Staff" })).toBeNull();
  expect(api.mock.calls.map(([path]) => path)).toEqual(["/api/v1/auth/lock-pin/"]);
});

it("lets anyone set their own lock PIN; a page PIN already set waits for the owner to reset it", async () => {
  renderAs("CASHIER");
  const card = (await screen.findByRole("heading", { name: "Lock PIN and private pages" })).closest("section");
  const fill = (pin, again = pin) => {
    fireEvent.change(within(card).getByLabelText("New PIN (4 to 6 numbers)"), { target: { value: pin } });
    fireEvent.change(within(card).getByLabelText("New PIN again"), { target: { value: again } });
    fireEvent.change(within(card).getByLabelText("Your sign-in password"), { target: { value: "Sign-in-1" } });
  };
  fill("4826", "4827");
  fireEvent.submit(within(card).getByRole("button", { name: "Save PIN" }).closest("form"));
  expect(await within(card).findByText("The two PINs are not the same.")).toBeInTheDocument();
  fill("4826");
  fireEvent.submit(within(card).getByRole("button", { name: "Save PIN" }).closest("form"));
  expect(await within(card).findByText(/Saved your lock PIN/)).toBeInTheDocument();
  expect([...within(card).getByLabelText("PIN to set").options].map((o) => o.value)).toEqual([""]);
  expect(within(card).getByText("M-Pesa PIN").nextSibling).toHaveTextContent("Set · 4 digits");
});

it("checks the new passwords match before sending", async () => {
  renderAs("CASHIER");
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "Old-pass-2026" } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: "New-pass-2026" } });
  fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "Other-pass-2026" } });
  fireEvent.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
  expect(api).not.toHaveBeenCalledWith("/api/v1/auth/password/change/", expect.anything());
});

it("lets the owner add a branch and refreshes the branch menu", async () => {
  const refresh = vi.fn();
  useAuth.mockReturnValue({ user: { roles: ["OWNER"], permissions: [] }, refresh });
  render(<MemoryRouter><SettingsPage /></MemoryRouter>);
  const form = (await screen.findByRole("heading", { name: "Add a branch" })).closest("form");
  expect(screen.getByText("Main branch")).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Branch name"), { target: { value: "Kiandas Market Stall" } });
  fireEvent.change(within(form).getByLabelText("Address"), { target: { value: "Kiandas" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add branch" }));
  await screen.findByText(/Added Kiandas Market Stall/);
  const body = JSON.parse(api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/branches/" && o?.method === "POST")[1].body);
  expect(body).toEqual({ name: "Kiandas Market Stall", address: "Kiandas" });
  await waitFor(() => expect(refresh).toHaveBeenCalled());
});

it("edits the main branch's location but only offers delete for other branches", async () => {
  renderAs("OWNER");
  fireEvent.click(await screen.findByRole("button", { name: "Edit Main branch" }));
  expect(screen.queryByRole("button", { name: "Delete Main branch" })).toBeNull();
  const form = screen.getByRole("heading", { name: "Edit Main branch" }).closest("form");
  fireEvent.change(within(form).getByLabelText("Address"), { target: { value: "Moi Avenue, Nairobi" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save branch" }));
  await screen.findByText("Branch details saved.");
  const [, patch] = api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/branches/1/" && o?.method === "PATCH");
  expect(JSON.parse(patch.body)).toMatchObject({ name: "Main branch", address: "Moi Avenue, Nairobi" });

  fireEvent.click(screen.getByRole("button", { name: "Delete Old stall" }));
  await screen.findByText("Deleted Old stall.");
  const { confirmAction } = await import("../../core/ui/alerts");
  expect(confirmAction).toHaveBeenCalledWith(expect.objectContaining({ title: "Delete Old stall?" }));
  expect(api).toHaveBeenCalledWith("/api/v1/tenancy/branches/2/", { method: "DELETE" });
});

it("shows a refused delete as a clear error directly below the branch list", async () => {
  const { ApiError } = await vi.importActual("../../core/api/client");
  const listed = api.getMockImplementation();
  api.mockImplementation(async (path, options = {}) => {
    if (path === "/api/v1/tenancy/branches/2/") throw new ApiError(400, "Old stall cannot be deleted because it has stock, ledger entries.");
    return listed(path, options);
  });
  renderAs("OWNER");
  fireEvent.click(await screen.findByRole("button", { name: "Delete Old stall" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveClass("formNoticeError");
  expect(alert).toHaveTextContent("Could not delete Old stall. Old stall cannot be deleted because it has stock, ledger entries.");
  expect(alert.previousElementSibling).toHaveClass("tableWrap");
});

it("keeps only the tools that fit when the business changes how it makes money", async () => {
  renderAs("OWNER");
  const business = (await screen.findByRole("heading", { name: "Business details" })).closest("form");
  expect(within(business).getByLabelText("Shelves & locations")).toBeInTheDocument();
  fireEvent.change(within(business).getByLabelText("How the business makes money"), { target: { value: "SERVICES" } });
  expect(within(business).queryByLabelText("Shelves & locations")).not.toBeInTheDocument();
  expect(within(business).queryByLabelText("Products & stock")).not.toBeInTheDocument();
  expect(within(business).getByRole("status")).toHaveTextContent("Products & stock, Point of sale turned off");
  fireEvent.change(within(business).getByLabelText("Kind of business"), { target: { value: "barber" } });
  fireEvent.click(within(business).getByLabelText("Services & jobs"));
  fireEvent.click(within(business).getByLabelText("Point of sale"));
  fireEvent.click(within(business).getByRole("button", { name: "Save business details" }));
  await screen.findByText("Business settings saved.");
  const saved = JSON.parse(api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/settings/" && o?.method === "PATCH")[1].body);
  expect(saved).toMatchObject({ business_model: "SERVICES", sector: "barber", business_type: "Barbershop" });
  expect(saved.enabled_modules.sort()).toEqual(["pos", "services"]);
});

it("shows tools outside a Basic plan as locked instead of letting the owner tick them", async () => {
  const basic = { ...settings, enabled_modules: ["inventory", "pos", "reports"], plan_modules: ["customers", "expenses", "inventory", "mpesa", "pos", "services"],
    plan: { code: "BASIC", name: "Basic", complimentary: false, ended: false, includes: ["inventory", "services", "pos", "customers", "expenses", "mpesa"], waiting: ["reports"] } };
  const usual = api.getMockImplementation();
  api.mockImplementation(async (path, options = {}) => (path === "/api/v1/tenancy/settings/" && !options.method ? basic : usual(path, options)));
  renderAs("OWNER");
  const business = (await screen.findByRole("heading", { name: "Business details" })).closest("form");
  for (const tool of ["Reports", "Staff", "Branches", "Shelves & locations"]) {
    const box = within(business).getByRole("checkbox", { name: new RegExp(`^${tool}`) });
    expect(box).toBeDisabled();
    expect(box).not.toBeChecked();   // even Reports, which was chosen at set-up
  }
  expect(within(business).getByRole("checkbox", { name: "Customers" })).toBeEnabled();
  expect(within(business).getByRole("link", { name: "Upgrade to Pro" })).toHaveAttribute("href", "/admin/subscription");
  // The plan the business is on, what it includes, and what was chosen but waits for Pro.
  const plan = within(business).getByRole("region", { name: "Your plan" });
  expect(within(plan).getByRole("heading", { name: "Plan: Basic" })).toBeInTheDocument();
  expect(plan).toHaveTextContent("Includes: Products & stock, Services & jobs, Point of sale, Customers, Expenses, M-Pesa agency.");
  expect(plan).toHaveTextContent("switched off until you are on Pro: Reports");
  expect(within(plan).getByRole("link", { name: "Change plan" })).toHaveAttribute("href", "/admin/subscription");
});


it("lets the owner keep a staff member out of the pages they choose", async () => {
  renderAs("OWNER");
  expect(await screen.findByLabelText("jane cannot open Money lent")).toBeChecked();  // what Jane is kept out of now
  fireEvent.click(screen.getByLabelText("jane cannot open M-Pesa agency"));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/tenancy/staff/2/", expect.objectContaining({ method: "PATCH" })));
  const [, options] = api.mock.calls.find(([path, o]) => path === "/api/v1/tenancy/staff/2/" && o?.method === "PATCH");
  expect(JSON.parse(options.body)).toEqual({ hidden_pages: ["loans", "mpesa"] });
  expect(screen.getByText("Every page")).toBeInTheDocument();
});

it("lets the owner tick an employee's work pages and reset their sign-in or PINs", async () => {
  renderAs("OWNER");
  expect(await screen.findByLabelText("kim can open Selling")).toBeChecked();
  expect(screen.queryByLabelText("kim can open Money lent")).toBeNull();  // the owner's side is never offered
  expect(screen.getByText("Lock PIN set · M-Pesa PIN set")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("kim can open M-Pesa agency"));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/tenancy/staff/4/", expect.objectContaining({ method: "PATCH" })));
  expect(JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/tenancy/staff/4/")[1].body)).toEqual({ open_pages: ["sales", "mpesa"] });
  const row = screen.getByText("kim").closest("tr");
  fireEvent.click(within(row).getByRole("button", { name: "Reset sign-in" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/tenancy/staff/4/reset/", expect.anything()));
  expect(JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/tenancy/staff/4/reset/")[1].body)).toEqual({ what: "sign_in", password: "Sign-in-1" });
  fireEvent.click(within(row).getByRole("button", { name: "Reset PINs" }));
  await waitFor(() => expect(api.mock.calls.filter(([path]) => path === "/api/v1/tenancy/staff/4/reset/")).toHaveLength(2));
});

it("keeps letters out of a new PIN in Settings", async () => {
  renderAs("CASHIER");
  const card = (await screen.findByRole("heading", { name: "Lock PIN and private pages" })).closest("section");
  const pin = within(card).getByLabelText("New PIN (4 to 6 numbers)");
  pin.value = "12ab";
  fireEvent.input(pin);
  expect(pin).toHaveValue("12");
});
