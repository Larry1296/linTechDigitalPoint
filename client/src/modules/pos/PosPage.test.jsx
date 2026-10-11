import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PosPage } from "./PosPage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["commerce.add_sale", "commerce.change_payment"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));

const item = (id, name, price, category) => ({ id, product_name: name, variant_name: "Standard", sku: `S${id}`, selling_price: price,
  available: "10", product_type: "STOCK_ITEM", category_name: category });
const catalog = [item(1, "Charger", "300.00", "Power"), item(2, "Earphones", "450.00", "Audio"), item(3, "Cable", "150.00", "Power")];
let express;
let prompts;
beforeEach(() => {
  vi.clearAllMocks();
  express = { kind: "NONE", ready: false };
  prompts = [];
  api.mockImplementation(async (path, options = {}) => {
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return catalog;
    if (path === "/api/v1/commerce/mpesa-express/") return express;
    if (path === "/api/v1/commerce/pos/complete/") {
      const body = JSON.parse(options.body);
      return { sale_id: 5, receipt_number: "POS-5", total: "1050.00",
        waiting_payment: body.payment_method === "MPESA" ? { id: 61, method: "MPESA", amount: "1050.00", reference: "" } : undefined,
        ...(body.mpesa_phone ? { prompt: { id: 9, status: "PENDING", phone: "254712345678", amount: "1050.00" } } : {}) };
    }
    if (path === "/api/v1/commerce/prompts/9/") return prompts.shift() || { id: 9, status: "PENDING", phone: "254712345678", amount: "1050.00" };
    return [];
  });
});

const cart = () => screen.getByRole("heading", { name: "Current sale" }).closest("form");

it("adds up several products tapped in, with + and − on each line, and works out the change", async () => {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Earphones/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Cable/ }));
  fireEvent.click(within(cart()).getByRole("button", { name: "One more Charger" }));
  expect(within(cart()).getByText("4 items")).toBeInTheDocument();
  expect(within(cart()).getByRole("button", { name: /^Complete sale/ })).toHaveTextContent("1,200.00");
  fireEvent.click(within(cart()).getByRole("button", { name: "One less Charger" }));
  fireEvent.click(within(cart()).getByRole("button", { name: "Remove Cable" }));
  expect(within(cart()).getByRole("button", { name: /^Complete sale/ })).toHaveTextContent("750.00");
  // The category chips narrow the tiles.
  fireEvent.click(screen.getByRole("button", { name: "Audio" }));
  expect(screen.queryByRole("heading", { name: "Power" })).not.toBeInTheDocument();
  fireEvent.change(within(cart()).getByLabelText("Cash received"), { target: { value: "1000" } });
  expect(within(cart()).getByText(/Change:/)).toHaveTextContent("250.00");
});

it("sends an M-Pesa prompt to the customer's phone and shows it paid", async () => {
  express = { kind: "TILL", ready: true };
  prompts = [{ id: 9, status: "COMPLETED", phone: "254712345678", amount: "1050.00", receipt_number: "SJK4H7XQ2P", detail: "Paid." }];
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  fireEvent.click(within(cart()).getByLabelText("M-Pesa"));
  fireEvent.change(within(cart()).getByLabelText("Customer's M-Pesa number"), { target: { value: "0712345678" } });
  await act(async () => { fireEvent.click(within(cart()).getByRole("button", { name: /^Complete sale & send prompt/ })); });
  const sent = JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/commerce/pos/complete/")[1].body);
  expect(sent).toEqual(expect.objectContaining({ payment_method: "MPESA", mpesa_phone: "0712345678" }));
  const done = screen.getByRole("region", { name: "Sale complete" });
  expect(within(done).getByText(/Prompt sent to 0712345678/)).toBeInTheDocument();
  await waitFor(() => expect(within(done).getByText(/M-Pesa code SJK4H7XQ2P/)).toBeInTheDocument(), { timeout: 5000 });
  expect(within(done).getByText("Payment confirmed (SJK4H7XQ2P).")).toBeInTheDocument();
  expect(within(done).queryByRole("group", { name: "Confirm M-Pesa payment" })).toBeNull();
});

it("without a till set up, M-Pesa is confirmed by its code as before", async () => {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /^Charger/ }));
  fireEvent.click(within(cart()).getByLabelText("M-Pesa"));
  expect(within(cart()).queryByLabelText("Customer's M-Pesa number")).toBeNull();
  await act(async () => { fireEvent.click(within(cart()).getByRole("button", { name: /^Complete sale/ })); });
  const box = screen.getByRole("group", { name: "Confirm M-Pesa payment" });
  expect(within(box).queryByRole("button", { name: /Send M-Pesa prompt/ })).toBeNull();
  expect(within(box).getByLabelText(/M-Pesa code/)).toBeInTheDocument();
});
