import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { QuickReceivePage } from "./QuickReceivePage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async () => ({ id: 4, receipt_number: "RCV-1" })) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({
  ProductSearch: ({ onSelect }) => <button type="button" onClick={() => onSelect({ id: 7, product_name: "Omo", variant_name: "500g", sku: "OMO500" })}>Pick Omo</button>,
}));
beforeEach(() => vi.clearAllMocks());
const sent = () => JSON.parse(api.mock.calls[0][1].body);
const add = async () => { await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add to my stock" })); }); };

it("adds stock already in the shop as opening stock: no supplier, and an unknown price is cost pending", async () => {
  render(<MemoryRouter><QuickReceivePage defaultSource="OPENING" /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "Add stock you already have" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Supplier")).not.toBeInTheDocument();
  expect(screen.queryByText("Delivery and other costs")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Pick Omo" }));
  fireEvent.change(screen.getByLabelText("How many you have now"), { target: { value: "12" } });
  await add();
  expect(sent()).toMatchObject({ document_status: "OPENING_BALANCE", lines: [{ variant_id: 7, received_quantity: "12", uncosted: true, placements: [] }] });
  expect(sent().payment).toBeUndefined();
  expect(screen.getByText(/12 × Omo 500g added \(cost pending\)/)).toBeInTheDocument();

  api.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "Pick Omo" }));
  fireEvent.change(screen.getByLabelText("How many you have now"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText(/Buying price for one/), { target: { value: "110" } });
  await add();
  expect(sent().lines[0]).toEqual({ variant_id: 7, received_quantity: "3", unit_cost: "110", placements: [] });
});

it("opens as a supplier purchase by default and still asks for the supplier", async () => {
  render(<MemoryRouter><QuickReceivePage /></MemoryRouter>);
  expect(screen.getByRole("button", { name: /Bought from a supplier/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("Supplier")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Stock I already have/ }));
  expect(screen.queryByLabelText("Supplier")).not.toBeInTheDocument();
});

