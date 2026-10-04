import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../receipts/ReceiptPanel", () => ({ ReceiptPanel: () => null }));
const perms = vi.hoisted(() => ({ list: [] }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: perms.list } }) }));
import { api } from "../../core/api/client";
import { CyberIncomePage, CyberServiceIncomePage } from "./CyberIncomePage";

const STAFF = ["cyber.view_cyberjob", "cyber.add_cyberjob", "cyber.complete_cyber_job"];
const OWNER = [...STAFF, "cyber.change_cyberjobline", "cyber.add_cyberserviceprofile", "cyber.change_cyberserviceprofile", "catalog.add_product",
  "catalog.add_productvariant", "catalog.change_productvariant", "catalog.change_product", "catalog.add_category", "accounting.view_profit"];
const p = (amount = "0", units = "0", times = 0) => ({ amount, units, times });
const periods = (amount, units, times) => ({ today: p(amount, units, times), week: p(amount, units, times), month: p(amount, units, times) });
const option = (id, name, extra = {}) => ({ id, name, price: "10.00", minimum_price: "0.00", billing_unit: "PER_PAGE", price_varies: false, active: true,
  cost: "0.00", ...periods(), ...extra });
const GROUPS = [{ id: 1, name: "Printing & Copying", subgroups: [] }, { id: 3, name: "Finishing & Files", subgroups: [] },
  { id: 2, name: "Online Applications", subgroups: [{ id: 21, name: "Government & KRA" }, { id: 22, name: "NTSA & Education" }] }];
const printing = { id: 4, name: "Printing", notes: "", active: true, group: { id: 1, name: "Printing & Copying" }, subgroup: null, ...periods("400.00", "40", 2),
  options: [option(41, "Single side", { minimum_price: "8.00", ...periods("400.00", "40", 2) }), option(42, "Both sides", { price: "15.00" })] };
const lamination = { id: 9, name: "Lamination", notes: "", active: true, group: { id: 3, name: "Finishing & Files" }, subgroup: null, ...periods(),
  options: [option(91, "ID card", { price: "30.00", billing_unit: "PER_ITEM" }), option(92, "A4", { price: "50.00", billing_unit: "PER_ITEM" })] };
const kra = { id: 7, name: "KRA PIN registration / retrieval", notes: "Service fee only", active: true, group: { id: 2, name: "Online Applications" },
  subgroup: { id: 21, name: "Government & KRA" }, ...periods(),
  options: [option(71, "Standard", { price: "0.00", billing_unit: "FIXED" })] };

beforeEach(() => { vi.clearAllMocks(); perms.list = STAFF; });

const overview = async () => {
  api.mockImplementation(async (path, options) => (options?.method === "POST" ? { ...printing } : {
    services: [printing, lamination, kra], groups: GROUPS, totals: { today: "400.00", week: "400.00", month: "400.00" } }));
  render(<MemoryRouter><CyberIncomePage /></MemoryRouter>);
  return screen.findByRole("form", { name: "Record income" });
};

it("records income by group, then service and price option; the amount fills in and follows the option's rules", async () => {
  const form = await overview();
  expect(within(form).queryByLabelText("Service")).toBeNull();  // the group comes first
  expect(within(within(form).getByLabelText("Group")).getAllByRole("option").map((o) => o.textContent))
    .toEqual(["Choose the group", "Printing & Copying", "Finishing & Files", "Online Applications"]);
  fireEvent.change(within(form).getByLabelText("Group"), { target: { value: "1" } });
  expect(within(within(form).getByLabelText("Service")).queryByRole("option", { name: "KRA PIN registration / retrieval" })).toBeNull();
  fireEvent.change(within(form).getByLabelText("Service"), { target: { value: "4" } });
  fireEvent.change(within(form).getByLabelText("Price option"), { target: { value: "42" } });
  fireEvent.change(within(form).getByLabelText("How many pages"), { target: { value: "10" } });
  expect(within(form).getByLabelText(/Amount charged/)).toHaveValue(150);
  expect(within(form).getByLabelText(/Amount charged/)).toHaveAttribute("readonly");  // fixed price for staff
  fireEvent.change(within(form).getByLabelText("Price option"), { target: { value: "41" } });
  fireEvent.change(within(form).getByLabelText("How many pages"), { target: { value: "10" } });
  expect(within(form).getByText(/^KSh 10 per page, can go down to KSh 8/)).toHaveTextContent("KSh 100 in all");
  fireEvent.change(within(form).getByLabelText(/Amount charged/), { target: { value: "70" } });
  expect(within(form).getByText("The lowest for this is KSh 80.")).toBeInTheDocument();
  expect(within(form).getByRole("button", { name: "Record income" })).toBeDisabled();
  fireEvent.change(within(form).getByLabelText(/Amount charged/), { target: { value: "85" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record KSh 85" })); });
  const [path, options] = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(path).toBe("/api/v1/cyber/income/record/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ lines: [{ option_id: 41, quantity: "10", amount: "85" }], payment_method: "CASH" }));
});

it("asks for the amount when a service has no price yet, and lists revenue by group with links to each service's page", async () => {
  const form = await overview();
  fireEvent.change(within(form).getByLabelText("Group"), { target: { value: "2" } });
  expect(within(form).getByRole("group", { name: "Government & KRA" })).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Service"), { target: { value: "7" } });
  expect(within(form).queryByLabelText("Price option")).toBeNull();
  expect(within(form).getByLabelText(/Amount charged/)).toHaveAttribute("placeholder", "Type the amount");
  fireEvent.change(within(form).getByLabelText(/Amount charged/), { target: { value: "200" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record KSh 200" })); });
  expect(JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body)).toEqual(expect.objectContaining({ lines: [{ option_id: 71, quantity: "1", amount: "200" }] }));
  const row = screen.getByRole("link", { name: "Printing" }).closest("tr");
  expect(screen.getByRole("link", { name: "Printing" })).toHaveAttribute("href", "/admin/cyber/income/4");
  const printingGroup = row.closest("tbody");
  expect(within(printingGroup).getByRole("rowheader", { name: "Printing & Copying" }).closest("tr")).toHaveTextContent("KSh 400");
  expect(screen.getByRole("rowheader", { name: "Government & KRA" })).toBeInTheDocument();
  expect(row).toHaveTextContent("2 price options");
  expect(row).toHaveTextContent("2 sales");
});

it("opens a service as a full page where the owner adds and edits price options", async () => {
  perms.list = OWNER;
  api.mockImplementation(async (path, options) => (options?.method === "POST"
    ? { ...printing, options: [...printing.options, option(43, "Bulk 50+ pages", { price: "7.00" })], history: [], groups: GROUPS }
    : options?.method === undefined ? { ...printing, history: [], groups: GROUPS } : null));
  render(<MemoryRouter initialEntries={["/admin/cyber/income/4"]}><Routes><Route path="/admin/cyber/income/:serviceId" element={<CyberServiceIncomePage />} /></Routes></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Printing", level: 1 })).toBeInTheDocument();
  expect(screen.getByText("Printing & Copying", { selector: "p" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Service")).toBeNull();  // the service is already chosen on its own page
  fireEvent.click(screen.getByRole("button", { name: "Add a price option" }));
  const add = screen.getByRole("form", { name: "Add price option" });
  fireEvent.change(within(add).getByLabelText("Option name"), { target: { value: "Bulk 50+ pages" } });
  fireEvent.change(within(add).getByLabelText(/^Price/), { target: { value: "7" } });
  fireEvent.change(within(add).getByLabelText(/Your cost per unit/), { target: { value: "3" } });
  await act(async () => { fireEvent.click(within(add).getByRole("button", { name: "Add option" })); });
  const [path, options] = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(path).toBe("/api/v1/cyber/income/4/options/");
  expect(JSON.parse(options.body)).toEqual({ name: "Bulk 50+ pages", billing_unit: "PER_PAGE", price: "7", price_varies: false, minimum_price: "0", cost: "3", active: true });
  expect(await screen.findByText("Bulk 50+ pages")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit Both sides" }));
  const edit = screen.getByRole("form", { name: "Edit price option" });
  fireEvent.click(within(edit).getByLabelText(/The amount varies/));
  expect(within(edit).queryByLabelText(/Lowest price/)).toBeNull();
  await act(async () => { fireEvent.click(within(edit).getByRole("button", { name: "Save option" })); });
  expect(JSON.parse(api.mock.calls.filter(([, o]) => o?.method === "POST")[1][1].body)).toEqual(expect.objectContaining({ name: "Both sides", price_varies: true, active: true }));
});

it("lets the owner move a service to another group from its page", async () => {
  perms.list = OWNER;
  api.mockImplementation(async (path) => (path.endsWith("/settings/")
    ? { ...kra, history: [], groups: GROUPS, subgroup: { id: 22, name: "NTSA & Education" } } : { ...kra, history: [], groups: GROUPS }));
  render(<MemoryRouter initialEntries={["/admin/cyber/income/7"]}><Routes><Route path="/admin/cyber/income/:serviceId" element={<CyberServiceIncomePage />} /></Routes></MemoryRouter>);
  expect(await screen.findByText(/Online Applications › Government & KRA/, { selector: "p" })).toBeInTheDocument();
  fireEvent.click(screen.getByText("Change name, group or note"));
  const form = screen.getByRole("form", { name: "Service details" });
  expect(within(form).getByLabelText("Group")).toHaveValue("21");
  fireEvent.change(within(form).getByLabelText("Group"), { target: { value: "22" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Save" })); });
  expect(JSON.parse(api.mock.calls.find(([p]) => p.endsWith("/settings/"))[1].body)).toEqual({ name: "KRA PIN registration / retrieval", notes: "Service fee only", category_id: 22 });
  expect(await screen.findByText(/Online Applications › NTSA & Education/, { selector: "p" })).toBeInTheDocument();
});

it("records one customer's visit: colour printing with design for 30 and three A4 laminations at 50, on one receipt", async () => {
  const colour = option(43, "Colour with design", { price: "0.00", billing_unit: "FIXED", price_varies: true });
  const withColour = { ...printing, options: [...printing.options, colour] };
  api.mockImplementation(async (path, opts) => (opts?.method === "POST" ? { sale_id: 5, receipt_number: "CYB-5", total: "180.00" } : {
    services: [withColour, lamination, kra], groups: GROUPS, totals: { today: "0", week: "0", month: "0" } }));
  render(<MemoryRouter><CyberIncomePage /></MemoryRouter>);
  const form = await screen.findByRole("form", { name: "Record income" });
  const first = within(form).getByRole("group", { name: "Service 1" });
  fireEvent.change(within(first).getByLabelText("Group"), { target: { value: "1" } });
  fireEvent.change(within(first).getByLabelText("Service"), { target: { value: "4" } });
  fireEvent.change(within(first).getByLabelText("Price option"), { target: { value: "43" } });
  fireEvent.change(within(first).getByLabelText(/Amount charged/), { target: { value: "30" } });
  fireEvent.click(within(form).getByRole("button", { name: "+ Add another service" }));
  const second = within(form).getByRole("group", { name: "Service 2" });
  fireEvent.change(within(second).getByLabelText("Group"), { target: { value: "3" } });
  fireEvent.change(within(second).getByLabelText("Service"), { target: { value: "9" } });
  fireEvent.change(within(second).getByLabelText("Price option"), { target: { value: "92" } });
  fireEvent.change(within(second).getByLabelText("How many items"), { target: { value: "3" } });
  expect(within(second).getByLabelText(/Amount charged/)).toHaveValue(150);
  const summary = within(form).getByRole("list", { name: "This visit" });
  expect(summary).toHaveTextContent("Printing (Colour with design)KSh 30");
  expect(summary).toHaveTextContent("Lamination (A4) × 3KSh 150");
  expect(summary).toHaveTextContent("TotalKSh 180");
  fireEvent.change(within(form).getByLabelText("Paid by"), { target: { value: "MPESA" } });
  fireEvent.change(within(form).getByLabelText("M-Pesa code"), { target: { value: "SJK4ABC123" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Record KSh 180" })); });
  const [path, opts] = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(path).toBe("/api/v1/cyber/income/record/");
  expect(JSON.parse(opts.body)).toEqual(expect.objectContaining({ payment_method: "MPESA", payment_reference: "SJK4ABC123",
    lines: [{ option_id: 43, quantity: "1", amount: "30" }, { option_id: 92, quantity: "3" }] }));
  expect(await screen.findByText(/KSh 180 recorded for 2 services on one receipt/)).toBeInTheDocument();
});

it("lets the owner add a service from the dropdowns; it is then picked on that line, ready to record", async () => {
  perms.list = OWNER;
  const binding = { id: 12, name: "Binding", notes: "", active: true, group: { id: 3, name: "Finishing & Files" }, subgroup: null, ...periods(),
    options: [option(121, "Standard", { price: "0.00", billing_unit: "FIXED", price_varies: true })] };
  let services = [printing, lamination, kra];
  api.mockImplementation(async (path, options) => {
    if (options?.method === "POST") { services = [...services, binding]; return binding; }
    return { services, groups: GROUPS, totals: { today: "0", week: "0", month: "0" } };
  });
  render(<MemoryRouter><CyberIncomePage /></MemoryRouter>);
  const form = await screen.findByRole("form", { name: "Record income" });
  fireEvent.change(within(form).getByLabelText("Group"), { target: { value: "3" } });
  fireEvent.click(within(form).getByRole("button", { name: "+ New service" }));
  const adding = screen.getAllByRole("form", { name: "Add a service" }).at(0);
  expect(within(adding).getByLabelText("Group")).toHaveValue("3");  // the group the line was on
  fireEvent.change(within(adding).getByLabelText("Service name"), { target: { value: "Binding" } });
  fireEvent.click(within(adding).getByLabelText(/The amount varies/));
  await act(async () => { fireEvent.click(within(adding).getByRole("button", { name: "Add service" })); });
  const [path, options] = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(path).toBe("/api/v1/cyber/income/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ name: "Binding", category_id: 3, price_varies: true }));
  expect(within(form).getByLabelText("Service")).toHaveValue("12");
  expect(within(form).getByLabelText(/Amount charged/)).toHaveAttribute("placeholder", "Type the amount");
  expect(screen.queryAllByRole("form", { name: "Add a service" })).toHaveLength(0);
});

it("lets the owner edit the chosen service's name, group and prices without leaving the form; staff see neither button", async () => {
  perms.list = OWNER;
  const form = await overview();
  fireEvent.change(within(form).getByLabelText("Group"), { target: { value: "1" } });
  fireEvent.change(within(form).getByLabelText("Service"), { target: { value: "4" } });
  fireEvent.click(within(form).getByRole("button", { name: /Edit Printing/ }));
  const editor = screen.getByRole("region", { name: "Edit Printing" });
  expect(within(editor).getByLabelText("Service name")).toHaveValue("Printing");
  fireEvent.click(within(editor).getByRole("button", { name: "Edit Both sides" }));
  fireEvent.click(within(editor).getByLabelText(/The amount varies/));
  await act(async () => { fireEvent.click(within(editor).getByRole("button", { name: "Save option" })); });
  const [path, options] = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(path).toBe("/api/v1/cyber/income/options/42/");
  expect(JSON.parse(options.body)).toEqual(expect.objectContaining({ name: "Both sides", price_varies: true }));
  fireEvent.click(within(editor).getByRole("button", { name: "Done" }));
  expect(screen.queryByRole("region", { name: "Edit Printing" })).toBeNull();
});

it("shows no add or edit buttons to staff without permission", async () => {
  const form = await overview();
  fireEvent.change(within(form).getByLabelText("Group"), { target: { value: "1" } });
  fireEvent.change(within(form).getByLabelText("Service"), { target: { value: "4" } });
  expect(within(form).queryByRole("button", { name: "+ New service" })).toBeNull();
  expect(within(form).queryByRole("button", { name: /Edit Printing/ })).toBeNull();
});
