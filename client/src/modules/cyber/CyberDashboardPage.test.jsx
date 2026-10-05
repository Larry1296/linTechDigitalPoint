import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", () => ({
  getCyberDashboard: vi.fn(async () => ({ today: { revenue: "0", jobs: 0, average: "0" }, active_jobs: 0, ready_jobs: 0 })),
  getCyberJobs: vi.fn(async () => []),
  getCyberServices: vi.fn(async () => [{ id: 1, variant: 11, product: 5, name: "Typing", variant_name: "Standard", selling_price: "50.00", billing_unit: "PER_PAGE", requires_job: true, active: true }]),
  createCyberJob: vi.fn(), deleteCyberJob: vi.fn(async () => undefined), deleteCyberSale: vi.fn(async () => ({})),
  createCyberService: vi.fn(), updateCyberService: vi.fn(), completeCyberJob: vi.fn(), transitionCyberJob: vi.fn(),
}));
vi.mock("../../core/api/client", () => ({ api: vi.fn(async () => ({ services: [], groups: [] })) }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true), askForm: vi.fn(), showError: vi.fn() }));
vi.mock("../receipts/ReceiptPanel", () => ({ ReceiptPanel: () => null }));
vi.mock("../../core/data/liveRefresh", () => ({ useLiveRefresh: () => {} }));
const perms = vi.hoisted(() => ({ list: [] }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: perms.list, organization: {} } }) }));
import * as cyber from "./api";
import { CyberDashboardPage } from "./CyberDashboardPage";

const job = (id, status, extra = {}) => ({ id, number: `CYB-${id}`, walk_in_customer_name: "Mary", status, total: "100.00", started_at: null, sale: null,
  lines: [{ id: id * 10, service_name: "Typing", quantity: "2" }], ...extra });
const renderDesk = async () => {
  await act(async () => { render(<MemoryRouter><CyberDashboardPage /></MemoryRouter>); });
  fireEvent.click(screen.getByRole("button", { name: "+ Take in a job for later" }));
  return screen.getByRole("form", { name: "New job" });
};

beforeEach(() => { vi.clearAllMocks(); perms.list = ["cyber.view_cyberjob", "cyber.add_cyberjob", "cyber.change_cyberjob", "cyber.delete_cyberjob"]; });

it("confirms a created job, clears the form and keeps Save job for later off so the same job is not made twice", async () => {
  let finish;
  cyber.createCyberJob.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const form = await renderDesk();
  const create = within(form).getByRole("button", { name: "Save job for later" });
  expect(create).toBeDisabled();  // no service chosen yet
  fireEvent.change(within(form).getByLabelText("Customer name (optional)"), { target: { value: "Mary" } });
  fireEvent.change(within(form).getByLabelText("Service 1"), { target: { value: "11" } });
  await act(async () => { fireEvent.click(create); });
  expect(within(form).getByRole("button", { name: "Saving job…" })).toBeDisabled();  // a second click does nothing
  fireEvent.click(within(form).getByRole("button", { name: "Saving job…" }));
  await act(async () => { finish({ id: 3, number: "CYB-261005-ABC123" }); });
  expect(cyber.createCyberJob).toHaveBeenCalledTimes(1);
  expect(within(form).getByText("Job CYB-261005-ABC123 created for Mary. It is waiting under Jobs.")).toBeInTheDocument();
  expect(within(form).getByLabelText("Service 1")).toHaveValue("0");
  expect(within(form).getByLabelText("Customer name (optional)")).toHaveValue("");
  expect(within(form).getByRole("button", { name: "Save job for later" })).toBeDisabled();
});

it("says so when a job could not be created, and lets the operator try again", async () => {
  cyber.createCyberJob.mockRejectedValue(new Error("Add at least one cyber service."));
  const form = await renderDesk();
  fireEvent.change(within(form).getByLabelText("Service 1"), { target: { value: "11" } });
  await act(async () => { fireEvent.click(within(form).getByRole("button", { name: "Save job for later" })); });
  expect(within(form).getByText("Add at least one cyber service.")).toBeInTheDocument();
  expect(within(form).getByRole("button", { name: "Save job for later" })).toBeEnabled();
});

it("offers Delete only on jobs not yet started, and deletes the job", async () => {
  cyber.getCyberJobs.mockResolvedValue([job(1, "QUEUED"), job(2, "IN_PROGRESS", { started_at: "2026-10-05T08:00:00Z" }), job(3, "READY")]);
  await renderDesk();
  expect(screen.queryByRole("button", { name: "Delete job CYB-2" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Delete job CYB-3" })).toBeNull();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete job CYB-1" })); });
  expect(cyber.deleteCyberJob).toHaveBeenCalledWith(1);
});

it("hides Delete from people without permission to delete jobs", async () => {
  perms.list = ["cyber.view_cyberjob", "cyber.add_cyberjob", "cyber.change_cyberjob"];
  cyber.getCyberJobs.mockResolvedValue([job(1, "QUEUED")]);
  await renderDesk();
  expect(screen.queryByRole("button", { name: "Delete job CYB-1" })).toBeNull();
});

it("deletes a paid job recorded wrongly, with a reason, so it can be recorded again", async () => {
  const { askForm } = await import("../../core/ui/alerts");
  perms.list = [...perms.list, "commerce.change_sale"];
  cyber.getCyberJobs.mockResolvedValue([job(4, "COMPLETED", { sale: 40 }), job(5, "COMPLETED", { sale: 50 })]);
  askForm.mockResolvedValueOnce({ reason: "Recorded wrongly" });
  await renderDesk();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete paid job CYB-4" })); });
  expect(cyber.deleteCyberSale).toHaveBeenCalledWith(40, "Recorded wrongly");
});

it("puts recording a service done first, and lists your services with Edit and Delete and a Create button", async () => {
  const { api } = await import("../../core/api/client");
  const { confirmAction } = await import("../../core/ui/alerts");
  perms.list = [...perms.list, "cyber.complete_cyber_job", "cyber.add_cyberserviceprofile", "catalog.add_product",
    "cyber.change_cyberserviceprofile", "cyber.delete_cyberserviceprofile"];
  const typing = { id: 3, name: "Typing", notes: "", active: true, group: null, subgroup: null,
    options: [{ id: 30, name: "Standard", price: "20.00", minimum_price: "0", billing_unit: "PER_PAGE", price_varies: false, active: true }] };
  api.mockImplementation(async (path) => (path.endsWith("/delete/") ? {} : { services: [typing], groups: [] }));
  await act(async () => { render(<MemoryRouter><CyberDashboardPage /></MemoryRouter>); });
  const record = screen.getByRole("form", { name: "Record income" });
  expect(within(record).getByRole("heading", { name: "Record a service done" })).toBeInTheDocument();
  expect(within(within(record).getByLabelText("Service")).getAllByRole("option").map((o) => o.textContent))
    .toEqual(["Choose the service done", "Typing", "+ Create a new service…"]);
  expect(screen.queryByRole("form", { name: "New job" })).toBeNull();  // taking in a job is under Jobs, behind its own button
  const card = screen.getByText("KSh 20 per page").closest("article");
  expect(within(card).getByRole("link", { name: "Edit Typing" })).toHaveAttribute("href", "/admin/cyber/income/3");
  await act(async () => { fireEvent.click(within(card).getByRole("button", { name: "Delete Typing" })); });
  expect(confirmAction).toHaveBeenCalled();
  expect(api).toHaveBeenCalledWith("/api/v1/cyber/income/3/delete/", { method: "POST" });
  fireEvent.click(screen.getByRole("button", { name: "+ Create a new service" }));
  expect(screen.getByRole("form", { name: "Create a new service" })).toHaveTextContent("This does not record a sale");
});
