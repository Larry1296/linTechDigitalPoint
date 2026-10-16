import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ExpensesPage } from "./LedgerPage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/data/liveRefresh", () => ({ useLiveRefresh: () => {} }));
const parts = [{ key: "SHOP", name: "Shop" }, { key: "CYBER", name: "Cyber café" }, { key: "MPESA", name: "M-Pesa" }];
const auth = vi.hoisted(() => ({ organization: null }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { organization: auth.organization } }) }));
const LINTECH = { enabled_modules: ["inventory", "pos", "services", "mpesa"], structure: "PARTS", money_mode: "ONE_DRAWER", parts };
let posted;
beforeEach(() => {
  vi.clearAllMocks();
  auth.organization = LINTECH;
  posted = null;
  api.mockImplementation(async (path, options) => {
    if (path === "/api/v1/accounting/categories/") return [{ id: 4, name: "Rent" }];
    if (path === "/api/v1/accounting/expenses/" && options?.method === "POST") { posted = JSON.parse(options.body); return {}; }
    if (path === "/api/v1/accounting/expenses/") return [{ id: 1, description: "October rent", category: "Rent", business_unit: "SHOP", amount: "6000",
      shares: { SHOP: "3000", CYBER: "2000", MPESA: "1000" }, paid: "6000", outstanding: "0", status: "PAID", incurred_on: "2026-10-01" }];
    return {};
  });
});
const fill = () => {
  fireEvent.change(screen.getByLabelText("What was it for?"), { target: { value: "October rent" } });
  fireEvent.change(screen.getByLabelText("Category"), { target: { value: "Rent" } });
  fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "6000" } });
};
const record = () => act(async () => { fireEvent.click(screen.getByRole("button", { name: "Record expense" })); });

it("shares a cost such as rent between the parts, by the amounts the owner enters", async () => {
  render(<ExpensesPage />);
  expect(await screen.findByText(/shared: Shop 3,000 · Cyber café 2,000 · M-Pesa 1,000/)).toBeInTheDocument();
  fill();
  fireEvent.click(screen.getByLabelText(/Shared by Shop, Cyber café and M-Pesa/));
  expect(screen.getByLabelText(/By what each part earned in the last 30 days/)).toBeChecked();
  fireEvent.click(screen.getByLabelText("I will enter each part's share"));
  fireEvent.change(screen.getByLabelText("Shop's share"), { target: { value: "3000" } });
  fireEvent.change(screen.getByLabelText("Cyber café's share"), { target: { value: "2000" } });
  expect(screen.getByRole("status")).toHaveTextContent("1000.00 still to share.");
  fireEvent.change(screen.getByLabelText("M-Pesa's share"), { target: { value: "1000" } });
  expect(screen.getByRole("status")).toHaveTextContent("The shares make the whole amount.");
  await record();
  expect(posted).toMatchObject({ amount: "6000", split: "AMOUNTS", shares: { SHOP: "3000", CYBER: "2000", MPESA: "1000" } });
});

it("records a cost for one part, or shares it by what each part earned", async () => {
  render(<ExpensesPage />);
  await screen.findByText("October rent");
  fill();
  fireEvent.click(screen.getByLabelText("Cyber café"));
  await record();
  expect(posted).toMatchObject({ business_unit: "CYBER" });
  expect(posted.split).toBeUndefined();
  fill();
  fireEvent.click(screen.getByLabelText(/Shared by/));
  await record();
  expect(posted).toMatchObject({ split: "INCOME", shares: {} });
});

it("asks which drawer paid a shared cost when each part keeps its own cash", async () => {
  auth.organization = { ...LINTECH, money_mode: "SEPARATE_CASH" };
  render(<ExpensesPage />);
  await screen.findByText("October rent");
  fill();
  fireEvent.click(screen.getByLabelText(/Shared by/));
  fireEvent.click(screen.getByLabelText("Equally between the parts"));
  fireEvent.change(screen.getByLabelText("Paid from which drawer?"), { target: { value: "MPESA" } });
  await record();
  expect(posted).toMatchObject({ split: "EVEN", business_unit: "MPESA" });
});

it("asks nothing about parts in a business run as one", async () => {
  auth.organization = { ...LINTECH, structure: "SINGLE" };
  render(<ExpensesPage />);
  await screen.findByText("October rent");
  expect(screen.queryByText("Which part of the business is it for?")).not.toBeInTheDocument();
  expect(screen.queryByText(/shared:/)).not.toBeInTheDocument();
});
