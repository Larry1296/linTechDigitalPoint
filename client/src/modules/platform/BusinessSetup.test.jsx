import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { BusinessSetupPage } from "./BusinessSetup";
import { modelFor, planFor, setupProblem, toggleModule } from "./businessSetupData";
import profiles from "./businessProfiles.fixture.json";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
const refresh = vi.fn(async () => {});
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 1, memberships: [] }, loading: false, refresh }) }));

const PLANS = [
  { code: "BASIC", name: "Basic", price: "500.00", currency: "KES", period_days: 30, description: "Basics", highlighted: false,
    enabled_modules: ["inventory", "services", "menu", "rooms", "pos", "customers", "expenses", "mpesa", "mkopa"] },
  { code: "PRO", name: "Pro", price: "1000.00", currency: "KES", period_days: 30, description: "Everything", highlighted: true, user_limit: null, branch_limit: null,
    enabled_modules: profiles.modules.map((module) => module.id) }];
// What the server suggests for a description (apps/tenancy/business_profiles.py suggest()), by the words in it.
const SUGGESTIONS = {
  kinyozi: { modules: ["services", "pos", "expenses", "reports"], matches: [{ id: "barber", label: "Barbershop" }], template: "barber", business_type: "Barbershop",
    categories: [], services: [{ name: "Haircut", billing_unit: "FIXED", requires_job: false }, { name: "Shave", billing_unit: "FIXED", requires_job: false }] },
  none: { modules: [], matches: [], template: "", business_type: "", categories: [], services: [] },
};
let suggestion = SUGGESTIONS.none;
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  suggestion = SUGGESTIONS.none;
  api.mockImplementation(async (path) => (path === "/api/v1/tenancy/business-profiles/" ? profiles
    : path.startsWith("/api/v1/tenancy/business-profiles/suggest/") ? suggestion
    : path.startsWith("/api/v1/tenancy/plans/") ? { trial_days: 30, plans: PLANS }
    : path === "/api/v1/tenancy/create/" ? { id: 9, name: "Created" } : {}));
});
const createBody = () => JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/tenancy/create/")[1].body);
const next = async () => { await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Continue" })); }); };
const describe = async (name, words, size) => {
  fireEvent.change(await screen.findByLabelText("Business name"), { target: { value: name } });
  fireEvent.change(screen.getByLabelText("Describe your business in your own words"), { target: { value: words } });
  if (size) fireEvent.click(screen.getByRole("button", { name: new RegExp(size) }));
  await next();
};
const ticked = (name) => screen.getByRole("button", { name }).getAttribute("aria-pressed") === "true";

it("works out how the business makes money from what it ticks, and which plan has it all", () => {
  expect(modelFor(new Set(["services", "pos"]))).toBe("SERVICES");
  expect(modelFor(new Set(["menu", "pos"]))).toBe("GOODS");
  expect(modelFor(new Set(["rooms", "menu"]))).toBe("MIXED");
  expect(modelFor(new Set(["mpesa"]))).toBe("SERVICES");
  expect(setupProblem(profiles, new Set(["reports", "expenses"]))).toBe("Tick at least one thing your business does to earn money.");
  expect(setupProblem(profiles, new Set(["mpesa", "expenses"]))).toBe("");
  // Turning on the till also turns on something to sell; any tool can be ticked.
  const on = toggleModule(profiles, "MIXED", new Set(["reports"]), "pos");
  expect([...on.modules].sort()).toEqual(["inventory", "pos", "reports"]);
  const off = toggleModule(profiles, "MIXED", new Set(["inventory", "services", "pos", "locations"]), "inventory");
  expect([...off.modules].sort()).toEqual(["pos", "services"]);
  expect(off.notes).toEqual(["Shelves & locations was turned off because it needs Products & stock."]);
  expect(planFor(PLANS, new Set(["services", "pos"])).code).toBe("BASIC");
  expect(planFor(PLANS, new Set(["services", "reports"])).code).toBe("PRO");
});

it("sets up a barbershop from the owner's own words, with the ticks and price list they suggest", async () => {
  suggestion = SUGGESTIONS.kinyozi;
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Your business" });
  await next();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter your business name.");
  await describe("Fresh Cuts", "A kinyozi: haircuts, shaves and beard trims", "Just me");

  expect(screen.getByRole("heading", { name: "What it does" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("We ticked what businesses like Barbershop usually use.");
  expect(screen.getByLabelText("What do you call your kind of business?")).toHaveValue("Barbershop");
  expect(ticked(/^Do work or services for customers/)).toBe(true);
  expect(ticked(/^Sell products I keep in stock/)).toBe(false);
  expect(ticked(/^Reports/)).toBe(true);
  // A one-person shop does not need reports on this plan: untick it.
  fireEvent.click(screen.getByRole("button", { name: /^Reports/ }));
  fireEvent.change(screen.getByLabelText("What do you call your kind of business?"), { target: { value: "Kinyozi" } });
  await next();

  expect(screen.getByRole("heading", { name: "Your starter list" })).toBeInTheDocument();
  expect(screen.queryByText("Product categories")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Price for Haircut"), { target: { value: "200" } });
  fireEvent.change(screen.getByLabelText("Price for Shave"), { target: { value: "100" } });
  await next();

  expect(screen.getByRole("heading", { name: "Your plan" })).toBeInTheDocument();
  expect(screen.getByText(/is the first plan with everything you ticked/)).toHaveTextContent("Basic is the first plan");
  expect(screen.getByRole("button", { name: /^Basic · KES 500 \/ month/ })).toHaveAttribute("aria-pressed", "true");
  await next();
  await next();  // location & money

  expect(screen.getByText("Fresh Cuts · Kinyozi · Just me")).toBeInTheDocument();
  expect(screen.getByText("Basic · first month free, then KES 500 / month")).toBeInTheDocument();
  expect(screen.getByText("Haircut KES 200, Shave KES 100")).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  const body = createBody();
  expect(body).toMatchObject({ name: "Fresh Cuts", business_type: "Kinyozi", description: "A kinyozi: haircuts, shaves and beard trims", sector: "barber",
    business_size: "SOLO", plan: "BASIC", starter_categories: [], structure: "SINGLE", money_mode: "ONE_DRAWER",
    starter_services: [{ name: "Haircut", selling_price: "200", billing_unit: "FIXED", requires_job: false },
      { name: "Shave", selling_price: "100", billing_unit: "FIXED", requires_job: false }] });
  expect(body).not.toHaveProperty("business_model");  // the server works it out from the tools
  expect(body.enabled_modules.sort()).toEqual(["expenses", "pos", "services"]);
  expect(refresh).toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "Add your logo" })).toBeInTheDocument();
}, 20000);  // a whole multi-step set-up: slow when every test file runs at once

it("sets up a business no list has, exactly as the owner defines it", async () => {
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await describe("Wanjiku Car Hire", "We hire out cars by the day and do airport transfers");
  // Nothing matched: nothing is ticked or named for them.
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await next();
  expect(screen.getByRole("alert")).toHaveTextContent("Say what you call your kind of business, in your own words.");
  fireEvent.change(screen.getByLabelText("What do you call your kind of business?"), { target: { value: "Car hire & airport transfers" } });
  await next();
  expect(screen.getByRole("alert")).toHaveTextContent("Tick at least one thing your business does to earn money.");
  fireEvent.click(screen.getByRole("button", { name: /^Do work or services for customers/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Point of sale/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Customers/ }));
  await next();
  fireEvent.click(screen.getByRole("button", { name: /Add a service/ }));
  fireEvent.change(screen.getByPlaceholderText("Service name"), { target: { value: "Car hire a day" } });
  fireEvent.change(screen.getByLabelText("Price for Car hire a day"), { target: { value: "4500" } });
  await next();
  await next();  // Basic has everything ticked
  await next();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  expect(createBody()).toMatchObject({ business_type: "Car hire & airport transfers", sector: "", plan: "BASIC",
    starter_services: [{ name: "Car hire a day", selling_price: "4500", billing_unit: "FIXED", requires_job: false }] });
  expect(createBody().enabled_modules.sort()).toEqual(["customers", "pos", "services"]);
}, 20000);

it("recommends the plan with every tool ticked and explains what a smaller plan leaves out", async () => {
  suggestion = SUGGESTIONS.kinyozi;
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await describe("Fresh Cuts", "kinyozi");
  await next();  // keeps Reports
  await next();  // starter list
  expect(screen.getByRole("button", { name: /^Pro · KES 1,000 \/ month/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: /^Basic · KES 500/ })).toHaveTextContent("Does not include: Reports");
  fireEvent.click(screen.getByRole("button", { name: /^Basic · KES 500/ }));
  await next();
  expect(screen.getByRole("alert")).toHaveTextContent("Reports is not in Basic. Choose Pro, or go back and leave it off.");
}, 20000);

it("resumes where the owner stopped after the page reloads, and forgets the draft once the business exists", async () => {
  suggestion = SUGGESTIONS.kinyozi;
  const first = render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await describe("Fresh Cuts", "kinyozi");
  await next();
  fireEvent.change(screen.getByLabelText("Price for Haircut"), { target: { value: "200" } });
  first.unmount();

  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Your starter list" })).toBeInTheDocument();
  expect(screen.getByLabelText("Price for Haircut")).toHaveValue(200);
  await next(); await next(); await next();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  expect(createBody()).toMatchObject({ name: "Fresh Cuts", sector: "barber", starter_services: [expect.objectContaining({ name: "Haircut", selling_price: "200" })] });
  expect(sessionStorage.getItem("business-setup-draft:1")).toBeNull();
}, 20000);

it("sets up an M-Pesa agent with only the agency, without stock or a till", async () => {
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await describe("Juma Agency", "");
  fireEvent.change(screen.getByLabelText("What do you call your kind of business?"), { target: { value: "M-Pesa agent" } });
  fireEvent.click(screen.getByRole("button", { name: /^Run an M-Pesa agency/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Expenses/ }));
  await next();
  // No products, services, menu or rooms: no starter list step.
  expect(screen.getByRole("heading", { name: "Your plan" })).toBeInTheDocument();
  await next(); await next();
  expect(screen.getByText("M-Pesa agency", { selector: "dd" })).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  expect(createBody().enabled_modules.sort()).toEqual(["expenses", "mpesa"]);
  expect(createBody().chama).toBeNull();
}, 20000);
