import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { BusinessSetupPage } from "./BusinessSetup";
import { fitModules, moduleProblem, searchSectors, toggleModule } from "./businessSetupData";
import profiles from "./businessProfiles.fixture.json";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
const refresh = vi.fn(async () => {});
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 1, memberships: [] }, loading: false, refresh }) }));
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  api.mockImplementation(async (path) => (path === "/api/v1/tenancy/business-profiles/" ? profiles
    : path === "/api/v1/tenancy/plans/" ? { trial_days: 30, plans: [
      { code: "BASIC", name: "Basic", price: "500.00", currency: "KES", description: "Basics", enabled_modules: ["inventory", "services", "pos", "customers", "expenses", "mpesa"] },
      { code: "PRO", name: "Pro", price: "1000.00", currency: "KES", description: "Everything", enabled_modules: ["inventory", "locations", "services", "pos", "customers", "expenses", "mpesa", "reports", "branches", "staff"] }] }
    : path === "/api/v1/tenancy/create/" ? { id: 9, name: "Created" } : {}));
});
const createBody = () => JSON.parse(api.mock.calls.find(([path]) => path === "/api/v1/tenancy/create/")[1].body);
const next = () => fireEvent.click(screen.getByRole("button", { name: "Continue" }));

it("keeps tools that need each other together, within what the business can use", () => {
  const on = toggleModule(profiles, "SERVICES", new Set(["reports"]), "pos");
  expect([...on.modules].sort()).toEqual(["pos", "reports", "services"]);
  expect(on.notes[0]).toBe("Services & jobs was turned on because Point of sale needs it.");
  const goods = toggleModule(profiles, "GOODS", new Set(), "pos");
  expect([...goods.modules].sort()).toEqual(["inventory", "pos"]);
  const off = toggleModule(profiles, "MIXED", new Set(["inventory", "services", "pos", "locations"]), "inventory");
  expect([...off.modules].sort()).toEqual(["pos", "services"]);   // POS still has services to sell
  expect(off.notes).toEqual(["Shelves & locations was turned off because it needs Products & stock."]);
  expect(fitModules(profiles, "SERVICES", new Set(["inventory", "pos", "locations", "mpesa"])).modules).toEqual(new Set(["mpesa"]));
  expect(moduleProblem(profiles, "MIXED", new Set(["reports"]))).toBe("Turn on Products & stock or Services & jobs.");
  expect(moduleProblem(profiles, "SERVICES", new Set(["mpesa"]))).toBe("");
  expect(searchSectors(profiles.sectors.SERVICES, "kinyozi").map((sector) => sector.id)).toEqual(["barber"]);
});

it("sets up a barbershop with its price list and never mentions stock or shelves", async () => {
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Your business" });
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter your business name.");
  fireEvent.change(screen.getByLabelText("Business name"), { target: { value: "Fresh Cuts" } });
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Choose how your business makes money.");
  fireEvent.click(screen.getByRole("button", { name: /I provide services/ }));
  fireEvent.click(screen.getByRole("button", { name: /Just me/ }));
  next();

  expect(screen.queryByRole("button", { name: /Mama mboga/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Search kinds of business"), { target: { value: "kinyozi" } });
  fireEvent.click(screen.getByRole("button", { name: /Barbershop/ }));
  next();

  expect(screen.getByRole("button", { name: /^Services & jobs/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: /^Point of sale/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("button", { name: /Products & stock/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Shelves/ })).not.toBeInTheDocument();
  expect(screen.queryByText("Product categories")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Price for Haircut"), { target: { value: "200" } });
  fireEvent.change(screen.getByLabelText("Price for Shave"), { target: { value: "100" } });
  next();
  next();
  next();

  expect(screen.getByText("Barbershop · I provide services")).toBeInTheDocument();
  expect(await screen.findByText(/stay locked until you upgrade to Pro/)).toHaveTextContent("Reports");  // once the plans have loaded
  fireEvent.click(screen.getByRole("button", { name: /Pro · KES 1,000/ }));
  expect(screen.queryByText(/stay locked until you upgrade/)).not.toBeInTheDocument();
  expect(screen.getByText("Haircut KES 200, Shave KES 100")).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  expect(createBody()).toMatchObject({ name: "Fresh Cuts", business_model: "SERVICES", sector: "barber", business_size: "SOLO",
    business_type: "Barbershop", plan: "PRO", starter_categories: [],
    starter_services: [{ name: "Haircut", selling_price: "200", billing_unit: "FIXED", requires_job: false },
      { name: "Shave", selling_price: "100", billing_unit: "FIXED", requires_job: false }] });
  expect(createBody().enabled_modules.sort()).toEqual(["expenses", "pos", "reports", "services"]);
  expect(refresh).toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "Add your logo" })).toBeInTheDocument();
}, 20000);  // a whole multi-step set-up: slow when every test file runs at once

it("sets up a business that does both, with its own description, categories and location", async () => {
  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("Business name"), { target: { value: "Kiandas Agrovet" } });
  fireEvent.click(screen.getByRole("button", { name: /Both goods and services/ }));
  next();
  fireEvent.click(screen.getByRole("button", { name: /Other mix of goods and services/ }));
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Describe what your business does.");
  fireEvent.change(screen.getByLabelText("Describe your business"), { target: { value: "Agrovet and vet clinic" } });
  next();

  expect(screen.getByRole("button", { name: /^Shelves & locations/ })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("New category"), { target: { value: "Animal feeds" } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  fireEvent.click(screen.getByRole("button", { name: /^Products & stock/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Services & jobs/ }));
  next();
  expect(screen.getByRole("alert")).toHaveTextContent("Turn on Products & stock or Services & jobs.");
  fireEvent.click(screen.getByRole("button", { name: /^Products & stock/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Services & jobs/ }));
  expect(screen.queryByRole("button", { name: /^Shelves & locations/ })).toHaveAttribute("aria-pressed", "false");  // turned off with stock
  next();

  fireEvent.change(screen.getByLabelText("First branch or shop name"), { target: { value: "Kiandas market stall" } });
  fireEvent.change(screen.getByLabelText("Country"), { target: { value: "UG" } });
  expect(screen.getByLabelText("Currency")).toHaveValue("UGX");
  next();
  fireEvent.change(screen.getByLabelText(/Cash in the till/), { target: { value: "15000" } });
  next();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  expect(createBody()).toMatchObject({ business_model: "MIXED", sector: "other_mixed", business_type: "Agrovet and vet clinic",
    starter_categories: ["Animal feeds"], starter_services: [], branch_name: "Kiandas market stall", country: "UG",
    currency: "UGX", timezone: "Africa/Kampala", opening_cash: "15000" });
});

it("resumes where the owner stopped after the page reloads, and forgets the draft once the business exists", async () => {
  sessionStorage.clear();
  const first = render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("Business name"), { target: { value: "Fresh Cuts" } });
  fireEvent.click(screen.getByRole("button", { name: /I provide services/ }));
  next();
  fireEvent.click(screen.getByRole("button", { name: /Barbershop/ }));
  next();
  fireEvent.change(screen.getByLabelText("Price for Haircut"), { target: { value: "200" } });
  first.unmount();

  render(<MemoryRouter><BusinessSetupPage /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Tools & starter list" })).toBeInTheDocument();
  expect(screen.getByLabelText("Price for Haircut")).toHaveValue(200);
  next(); next(); next();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create business workspace" })); });
  expect(createBody()).toMatchObject({ name: "Fresh Cuts", sector: "barber", starter_services: [expect.objectContaining({ name: "Haircut", selling_price: "200" })] });
  expect(sessionStorage.getItem("business-setup-draft:1")).toBeNull();
});
