import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ProductForm } from "./ProductForm";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async (path) => (path.includes("categories") ? [{ id: 9, name: "CYBER ESSENTIALS", path: "CYBER ESSENTIALS" }] : path.includes("brands") ? [] : {})) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [], organization: { enabled_modules: [] } } }) }));

it("adds paper sold 2 sheets for 5: the price is per pack and a ream counted in sheets is kept as packs", async () => {
  await act(async () => { render(<ProductForm zones={[]} onSaved={() => {}} defaults={{ category: "9" }} />); });
  fireEvent.change(screen.getByLabelText("Product name"), { target: { value: "A4 Printing Paper" } });
  fireEvent.click(screen.getByLabelText(/In packs: several pieces for one price/));
  fireEvent.change(screen.getByLabelText("One piece is called"), { target: { value: "sheet" } });
  expect(screen.getByLabelText("Variant")).toHaveValue("Pack of 2 sheets");
  fireEvent.change(screen.getByLabelText("Selling price for one pack of 2 sheets"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("How many sheets you have now"), { target: { value: "500" } });
  fireEvent.change(screen.getByLabelText("Buying price for one sheet"), { target: { value: "0.90" } });
  expect(screen.getByText("= 250 packs of 2, bought at 1.8 a pack.")).toBeInTheDocument();
  await act(async () => { fireEvent.submit(screen.getByRole("button", { name: "Create Product" }).closest("form")); });
  const sent = api.mock.calls.find(([path]) => path.includes("create-with-stock"))[1].body;
  expect(Object.fromEntries(sent)).toMatchObject({ name: "A4 Printing Paper", variant_name: "Pack of 2 sheets", selling_price: "5", pack_size: "2",
    piece_name: "sheet", opening_quantity: "250", opening_unit_cost: "1.8" });
});
