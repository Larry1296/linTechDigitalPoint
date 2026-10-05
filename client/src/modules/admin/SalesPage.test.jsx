import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ askForm: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["commerce.add_payment", "commerce.change_sale", "commerce.change_payment", "accounting.reverse_cashentry", "accounts.view_customerprofile"] } }) }));
import { api } from "../../core/api/client";
import { SalesPage } from "./SalesPage";

const sale = (id, extra) => ({ id, number: `POS-${id}`, created_at: "2026-09-25T12:15:00Z", customer: "Walk-in", status: "COMPLETED", due_date: null,
  total: "500.00", charged: "500.00", outstanding: "0.00", payments: [{ id, method: "CASH", amount: "500.00", status: "COMPLETED" }],
  items: [{ id, item: "C-C HEAD(45W) — C to C-HEAD", quantity: "1.000", list_price: "500.00", unit_price: "500.00", discount: "0.00", net_amount: "500.00", tax_amount: "0", returned_quantity: "0" }], ...extra });

it("shows one summary line per sale and the details only when it is opened", async () => {
  api.mockResolvedValue({ count: 2, results: [
    sale(1, { charged: "350.00", payments: [{ id: 1, method: "CASH", amount: "350.00", status: "COMPLETED" }] }),
    sale(2, { total: "800.00", charged: "800.00", outstanding: "300.00", customer: "Mary Achieng",
      items: [{ id: 2, item: "50W RECHARGEABLE BULB — 50W", quantity: "1.000", unit_price: "800.00", discount: "0", returned_quantity: "0" }] }),
  ] });
  render(<SalesPage />);
  const adapter = (await screen.findByText("C-C HEAD(45W)")).closest("details");
  expect(adapter).not.toHaveAttribute("open");
  expect(adapter.querySelector("summary")).toHaveTextContent("KSh 350");
  expect(adapter.querySelector("summary")).toHaveTextContent("was KSh 500");
  expect(adapter.querySelector("summary")).toHaveTextContent("Paid");
  expect(screen.getByText("50W RECHARGEABLE BULB").closest("summary")).toHaveTextContent("Owes KSh 300");
  expect(screen.queryByRole("button", { name: "Record payment" })).not.toBeVisible();
  fireEvent.click(adapter.querySelector("summary"));
  expect(adapter).toHaveAttribute("open");
});

it("after deleting a payment it folds the sale away and returns to its line, now showing what is owed", async () => {
  const glue = sale(3, { total: "50.00", charged: "50.00", payments: [{ id: 3, method: "CASH", amount: "50.00", status: "COMPLETED" }],
    items: [{ id: 3, item: "SUPER GLUE — 3g", quantity: "1.000", unit_price: "50.00", discount: "0", returned_quantity: "0" }] });
  let reversed = false;
  api.mockReset();
  api.mockImplementation(async (path) => {
    if (path.includes("/payments/3/delete/")) { reversed = true; return { id: 3, status: "REVERSED" }; }
    return { count: 1, results: [reversed ? { ...glue, outstanding: "50.00", payments: [{ ...glue.payments[0], status: "REVERSED" }] } : glue] };
  });
  render(<SalesPage />);
  const row = (await screen.findByText("SUPER GLUE")).closest("details");
  fireEvent.click(row.querySelector("summary"));
  const reverse = screen.getByText("Delete this payment").closest("details");
  fireEvent.click(reverse.querySelector("summary"));
  fireEvent.change(within(reverse).getByLabelText("Reason"), { target: { value: "Given on credit" } });
  fireEvent.click(screen.getByRole("button", { name: "Delete payment" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Payment of KSh 50 deleted");
  await waitFor(() => expect(row.querySelector("summary")).toHaveTextContent("Owes KSh 50"));
  expect(reverse).not.toHaveAttribute("open");
  expect(row).not.toHaveAttribute("open");
  expect(row.querySelector("summary")).toHaveFocus();
});

it("searches sales and can list only the ones still owed", async () => {
  api.mockReset();
  api.mockImplementation(async (path) => path.startsWith("/api/v1/commerce/customers/") ? [] : { count: 0, results: [] });
  render(<SalesPage />);
  await screen.findByText(/No sales yet/);
  fireEvent.click(screen.getByLabelText("Only sales that still owe money"));
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining("owing=1")));
  fireEvent.change(screen.getByLabelText("Find a sale"), { target: { value: "glue" } });
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringMatching(/q=glue.*owing=1|owing=1.*q=glue/)));
  expect(await screen.findByText(/No sales match/)).toBeInTheDocument();
});

it("lets a Walk-in debt be put under the customer who owes it", async () => {
  const glue = sale(4, { total: "50.00", charged: "50.00", outstanding: "50.00", customer_id: null, payments: [],
    items: [{ id: 4, item: "SUPER GLUE — 3g", quantity: "1.000", unit_price: "50.00", discount: "0", returned_quantity: "0" }] });
  let named = null;
  api.mockReset();
  api.mockImplementation(async (path, options) => {
    if (path === "/api/v1/commerce/customers/") return [{ id: 9, name: "John Otieno", phone: "0712345678" }];
    if (path.endsWith("/customer/")) { named = JSON.parse(options.body); return { id: 4, customer: "John Otieno" }; }
    return { count: 1, results: [named ? { ...glue, customer: "John Otieno", customer_id: 9 } : glue] };
  });
  render(<SalesPage />);
  const row = (await screen.findByText("SUPER GLUE")).closest("details");
  fireEvent.click(row.querySelector("summary"));
  const form = screen.getByRole("heading", { name: "Who owes this?" }).closest("form");
  await within(form).findByRole("option", { name: "John Otieno · 0712345678" });
  fireEvent.change(within(form).getByLabelText("Customer"), { target: { value: "9" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save customer" }));
  expect(await screen.findByRole("status")).toHaveTextContent("POS-4 is now under the customer you chose.");
  expect(named).toEqual({ customer_id: "9" });
  await waitFor(() => expect(row.querySelector("summary")).toHaveTextContent("John Otieno"));
  expect(screen.queryByRole("heading", { name: "Who owes this?" })).not.toBeInTheDocument();
});

it("shows a failed payment under the payment form, which stays open", async () => {
  const bulb = sale(5, { outstanding: "300.00", payments: [] });
  api.mockReset();
  api.mockImplementation(async (path, options) => {
    if (path.endsWith("/payments/") && options?.method === "POST") throw new Error("Payment exceeds the outstanding balance.");
    if (path === "/api/v1/commerce/customers/") return [];
    return { count: 1, results: [bulb] };
  });
  render(<SalesPage />);
  const row = (await screen.findByText("C-C HEAD(45W)")).closest("details");
  fireEvent.click(row.querySelector("summary"));
  const form = screen.getByRole("heading", { name: "Record a payment" }).closest("form");
  expect(within(form).getByLabelText("Amount received")).toHaveValue(300);
  fireEvent.click(within(form).getByRole("button", { name: "Record payment" }));
  expect(await within(form).findByRole("alert")).toHaveTextContent("Could not record the payment. Payment exceeds the outstanding balance.");
  expect(row).toHaveAttribute("open");
});

it("fills in the M-Pesa code typed at the sale, so confirming takes one click", async () => {
  api.mockResolvedValue({ count: 1, results: [sale(5, { outstanding: "50.00", total: "50.00", charged: "50.00",
    payments: [{ id: 5, method: "MPESA", amount: "50.00", status: "MANUAL_REVIEW", reference: "UJ5FF97VNX" }] })] });
  render(<SalesPage />);
  fireEvent.click((await screen.findByText("C-C HEAD(45W)")).closest("summary"));
  expect(screen.getByLabelText("M-Pesa code from the confirmation message")).toHaveValue("UJ5FF97VNX");
  expect(screen.getByRole("button", { name: "Confirm money received" })).toBeVisible();
});

it("deletes a whole sale recorded wrongly, with a reason, so it can be recorded again", async () => {
  api.mockReset();
  api.mockImplementation(async (path) => (path.endsWith("/delete/") ? { id: 7, status: "CANCELLED" } : { count: 1, results: [sale(7)] }));
  render(<SalesPage />);
  fireEvent.click((await screen.findByText("C-C HEAD(45W)")).closest("summary"));
  const remove = screen.getByText("Delete this sale").closest("details");
  fireEvent.click(remove.querySelector("summary"));
  fireEvent.change(within(remove).getByLabelText("Reason"), { target: { value: "Recorded twice" } });
  fireEvent.click(within(remove).getByRole("button", { name: "Delete sale" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/commerce/sales/7/delete/", expect.objectContaining({ method: "POST" })));
  expect(JSON.parse(api.mock.calls.find(([p]) => p.endsWith("/delete/"))[1].body)).toEqual({ reason: "Recorded twice" });
});

it("puts a Delete button on the line of a sale whose M-Pesa is not confirmed, and deletes the sale or only the payment", async () => {
  const { askForm } = await import("../../core/ui/alerts");
  const waiting = sale(8, { outstanding: "100.00", payments: [{ id: 81, method: "MPESA", amount: "100.00", status: "MANUAL_REVIEW", reference: "UJ53K9U3L5" }] });
  api.mockReset();
  api.mockImplementation(async (path) => (path.endsWith("/delete/") ? {} : { count: 2, results: [waiting, sale(9)] }));
  render(<SalesPage />);
  await screen.findAllByText("C-C HEAD(45W)");
  expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(1);  // only on the waiting sale
  askForm.mockResolvedValueOnce({ what: "sale", reason: "Recorded wrongly" });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/commerce/sales/8/delete/", { method: "POST", body: JSON.stringify({ reason: "Recorded wrongly" }) });
  askForm.mockResolvedValueOnce({ what: "payment", reason: "Wrong code" });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/commerce/payments/81/delete/", { method: "POST", body: JSON.stringify({ reason: "Wrong code" }) });
});
