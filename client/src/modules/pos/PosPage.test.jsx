import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PosPage } from "./PosPage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 1, permissions: ["commerce.add_sale", "commerce.change_payment", "accounts.view_customerprofile"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));

const item = (id, name, price, category) => ({ id, product_name: name, variant_name: "Standard", sku: `S${id}`, selling_price: price,
  available: "10", product_type: "STOCK_ITEM", category_name: category });
const catalog = [item(1, "Charger", "300.00", "Power"), item(2, "Earphones", "450.00", "Audio"), item(3, "Cable", "150.00", "Power")];
const payment = (code, amount, name, at = "2026-10-16T10:15:00+03:00") => ({ id: code.length, code, amount, paid_at: at, payer_name: name, payer_phone: "25470****149" });

// A stand-in for the server's checkout: nothing is sold until the payments cover the amount.
let express, open, checkout, arrivals, promptAnswer, customer;
const fresh = (total) => ({ id: 7, number: "POS-ABC123", status: "AWAITING", total, paid: "0", left: total, open: total, items: 1, cashier_id: 1,
  customer_id: customer, payments: [], till_payments: [] });
const paid = (payments) => ({ ...checkout, status: "COMPLETED", paid: checkout.total, left: "0", open: "0", payments,
  receipt: { sale_id: 5, receipt_number: checkout.number, total: checkout.total } });
beforeEach(() => {
  vi.clearAllMocks();
  express = { kind: "NONE", ready: false };
  open = [];
  arrivals = [];
  promptAnswer = null;
  customer = null;
  api.mockImplementation(async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : {};
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return catalog;
    if (path === "/api/v1/commerce/mpesa-express/") return express;
    if (path === "/api/v1/commerce/customers/") return [{ id: 12, name: "Wanjiru", phone: "0712345678" }];
    if (path === "/api/v1/commerce/pos/checkouts/" && options.method === "POST") {
      const total = body.items.reduce((sum, line) => sum + Number(catalog.find((p) => p.id === line.variant_id).selling_price) * line.quantity, 0).toFixed(2);
      checkout = fresh(total);
      return checkout;
    }
    if (path === "/api/v1/commerce/pos/checkouts/") return { checkouts: open };
    if (path === "/api/v1/commerce/pos/checkouts/7/") {
      checkout = promptAnswer ? paid([promptAnswer]) : { ...checkout, till_payments: arrivals };
      return checkout;
    }
    if (path === "/api/v1/commerce/pos/checkouts/7/pay/") {
      if (body.method === "CASH") checkout = paid([{ id: 1, method: "CASH", amount: checkout.total, status: "CONFIRMED", change: (Number(body.cash_given) - Number(checkout.total)).toFixed(2) }]);
      if (body.method === "TILL") {
        const chosen = arrivals.find((row) => row.id === body.incoming_id);
        checkout = paid([{ id: 2, method: "TILL", amount: chosen.amount, status: "CONFIRMED", reference: chosen.code, checked_with_safaricom: true }]);
      }
      if (body.method === "PROMPT") checkout = { ...checkout, open: "0", payments: [{ id: 3, method: "PROMPT", amount: checkout.total, status: "PENDING",
        prompt: { id: 9, status: "PENDING", phone: "254712345678", amount: checkout.total } }] };
      return checkout;
    }
    return [];
  });
});

const cart = () => screen.getByRole("heading", { name: "Current sale" }).closest("form");
const panel = () => screen.getByRole("region", { name: /^Checkout POS-ABC123/ });
const review = () => fireEvent.click(screen.getByRole("button", { name: /^Complete sale/ }));
const charge = async () => { if (!screen.queryByRole("dialog")) review(); await act(async () => { fireEvent.click(within(cart()).getByRole("button", { name: /^Charge/ })); }); };
const posted = (path) => api.mock.calls.filter(([p, o]) => p === path && o?.method === "POST").map(([, o]) => JSON.parse(o.body));

it("adds up the basket, and charging it sells nothing until the customer pays; cash gives change", async () => {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Earphones/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Cable/ }));
  // Picking products never opens the checkout; the bar keeps the sale so far.
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Sale so far" })).toHaveTextContent("3 items");
  review();
  fireEvent.click(within(cart()).getByRole("button", { name: "One more Charger" }));
  expect(within(cart()).getByText("4 items")).toBeInTheDocument();
  expect(within(cart()).getByRole("button", { name: /^Charge/ })).toHaveTextContent("1,200.00");
  fireEvent.click(within(cart()).getByRole("button", { name: "One less Charger" }));
  fireEvent.click(within(cart()).getByRole("button", { name: "Remove Cable" }));
  expect(within(cart()).getByRole("button", { name: /^Charge/ })).toHaveTextContent("750.00");
  await charge();
  expect(within(panel()).getByText("To pay")).toHaveTextContent("750.00");
  expect(posted("/api/v1/commerce/pos/complete/")).toEqual([]);  // the old sell-then-pay path is not used
  fireEvent.change(within(panel()).getByLabelText("Cash received"), { target: { value: "1000" } });
  expect(within(panel()).getByText(/Give change/)).toHaveTextContent("250.00");
  await act(async () => { fireEvent.click(within(panel()).getByRole("button", { name: /^Take .* cash/ })); });
  expect(posted("/api/v1/commerce/pos/checkouts/7/pay/")).toEqual([{ method: "CASH", cash_given: "1000" }]);
  const done = await screen.findByRole("region", { name: "Sale complete" });
  expect(within(done).getByText(/Sale complete · POS-ABC123/)).toBeInTheDocument();
  expect(within(done).getByText(/Give change/)).toHaveTextContent("250.00");
}, 20000);  // a whole sale, tap by tap: slow when every test file runs at once

it("records a customer who gave no cash as owing the whole price, once the customer is chosen there", async () => {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  await charge();
  fireEvent.change(within(panel()).getByLabelText("Cash received"), { target: { value: "0" } });
  expect(within(panel()).getByText(/Choose who owes KSh 300.00/)).toBeInTheDocument();
  const leave = within(panel()).getByRole("button", { name: "Leave KSh 300.00 owed by the customer" });
  expect(leave).toBeDisabled();
  fireEvent.change(within(panel()).getByLabelText("Customer"), { target: { value: "12" } });
  expect(leave).toBeEnabled();
  fireEvent.change(within(panel()).getByLabelText("Customer"), { target: { value: "12" } });
  expect(leave).toBeEnabled();
  await act(async () => { fireEvent.click(leave); });
  expect(posted("/api/v1/commerce/pos/checkouts/7/pay/")).toEqual([{ method: "OWED", due_date: null, customer_id: "12" }]);
}, 20000);

it("leaves the whole amount owed when the chosen customer gave no cash", async () => {
  customer = 12;
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  await charge();
  fireEvent.change(within(panel()).getByLabelText("Cash received"), { target: { value: "0" } });
  expect(within(panel()).getByText("The customer gave nothing, so KSh 300.00 is left owed by them.")).toBeInTheDocument();
  await act(async () => { fireEvent.click(within(panel()).getByRole("button", { name: "Leave KSh 300.00 owed by the customer" })); });
  expect(posted("/api/v1/commerce/pos/checkouts/7/pay/")).toEqual([{ method: "OWED", due_date: null }]);
}, 20000);

it("shows till payments as Safaricom reports them, and the cashier picks the customer's own", async () => {
  express = { kind: "TILL", ready: false, till_number: "9876543", till_notices: true };
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  await charge();
  fireEvent.click(within(panel()).getByRole("tab", { name: /Till/ }));
  expect(within(panel()).getByText(/Ask the customer to pay/)).toHaveTextContent("Till 9876543 exactly KSh 300.00");
  expect(within(panel()).getByText(/Waiting for the payment to arrive/)).toBeInTheDocument();
  // Two customers pay the same amount: both are shown, nothing is assumed.
  arrivals = [payment("SKA1111111", "300.00", "Wanjiru"), payment("SKB2222222", "300.00", "Otieno")];
  await waitFor(() => expect(within(panel()).getAllByRole("button", { name: "This is the customer's" })).toHaveLength(2), { timeout: 5000 });
  const otieno = within(panel()).getByText(/Otieno/).closest("li");
  expect(otieno).toHaveTextContent("SKB2222222");
  await act(async () => { fireEvent.click(within(otieno).getByRole("button", { name: "This is the customer's" })); });
  expect(posted("/api/v1/commerce/pos/checkouts/7/pay/")).toEqual([{ method: "TILL", incoming_id: 10 }]);
  expect(await screen.findByRole("region", { name: "Sale complete" })).toBeInTheDocument();
});

it("sends a prompt and the sale completes by itself when Safaricom confirms it", async () => {
  express = { kind: "TILL", ready: true, till_number: "9876543", till_notices: true };
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  await charge();
  fireEvent.click(within(panel()).getByRole("tab", { name: /Prompt/ }));
  fireEvent.change(within(panel()).getByLabelText("Customer's M-Pesa number"), { target: { value: "0712345678" } });
  await act(async () => { fireEvent.click(within(panel()).getByRole("button", { name: "Send prompt" })); });
  expect(within(panel()).getByText(/Prompt sent to 0712345678/)).toBeInTheDocument();
  promptAnswer = { id: 3, method: "PROMPT", amount: "300.00", status: "CONFIRMED", reference: "SJK4H7XQ2P" };
  expect(await screen.findByRole("region", { name: "Sale complete" }, { timeout: 5000 })).toBeInTheDocument();
});

it("a reloaded till picks up the cashier's checkout still waiting for payment", async () => {
  checkout = fresh("450.00");
  open = [{ ...checkout, cashier_id: 2, number: "POS-OTHER" }, checkout];  // a manager's list includes others' checkouts
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  expect(await screen.findByRole("region", { name: /^Checkout POS-ABC123/ })).toBeInTheDocument();
});

it("a till not connected to Safaricom takes the code as typed, and says it is not checked", async () => {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  await charge();
  fireEvent.click(within(panel()).getByRole("tab", { name: /Till/ }));
  expect(within(panel()).getByText(/not connected to Safaricom/)).toBeInTheDocument();
  expect(within(panel()).getByRole("button", { name: "Record payment" })).toBeDisabled();
  expect(within(panel()).queryByRole("tab", { name: /Prompt/ })).toBeNull();
});

it("opens the checkout only when asked, and going back to the products keeps the sale", async () => {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  expect(await screen.findByRole("button", { name: /^Complete sale/ })).toBeDisabled();
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  fireEvent.keyDown(document, { key: "F2" });
  expect(screen.getByRole("dialog", { name: "Complete the sale" })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^Earphones/ }));
  review();
  fireEvent.click(within(cart()).getByRole("button", { name: /Add more products/ }));
  expect(screen.getByRole("region", { name: "Sale so far" })).toHaveTextContent("750.00");
  // Taking payment cannot be closed by accident.
  await charge();
  expect(screen.queryByRole("button", { name: "Back to products" })).toBeNull();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(panel()).toBeInTheDocument();
});
