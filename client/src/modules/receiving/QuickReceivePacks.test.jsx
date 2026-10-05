import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { QuickReceivePage } from "./QuickReceivePage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async () => ({ id: 4, receipt_number: "RCV-1" })) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({
  ProductSearch: ({ onSelect }) => <button type="button" onClick={() => onSelect({ id: 9, product_name: "A4 Printing Paper", variant_name: "Pack of 2 sheets",
    sku: "PAPER-A4-2", pack_size: 2, piece_name: "sheet", available: "0" })}>Pick paper</button>,
}));

it("counts paper sold in packs of 2 in sheets: a ream of 500 at 0.90 a sheet is kept as 250 packs at 1.80", async () => {
  render(<MemoryRouter><QuickReceivePage defaultSource="OPENING" /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Pick paper" }));
  expect(screen.getByRole("note")).toHaveTextContent("sold in packs of 2 sheets");
  fireEvent.change(screen.getByLabelText("How many sheets you have now"), { target: { value: "500" } });
  fireEvent.change(screen.getByLabelText(/Buying price for one sheet/), { target: { value: "0.90" } });
  expect(screen.getByRole("status")).toHaveTextContent("= 250 packs of 2, bought at 1.8 a pack.");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add to my stock" })); });
  expect(JSON.parse(api.mock.calls[0][1].body).lines[0]).toEqual({ variant_id: 9, received_quantity: "250", unit_cost: "1.8", placements: [] });
});
