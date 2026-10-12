import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ProductForm } from "./ProductForm";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async (path) => (path.includes("categories") ? [{ id: 9, name: "EARPHONES", path: ["EARPHONES"] }]
  : path.includes("brands") ? [{ id: 3, name: "ORAIMO" }] : { product_id: 41, variant_id: 77 })) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: [], organization: { enabled_modules: [] } } }) }));

it("a similar product starts from the one it resembles and is received, not counted as stock already owned", async () => {
  const onSaved = vi.fn();
  await act(async () => { render(<ProductForm zones={[]} onSaved={onSaved} defaults={{ similarTo: "ORAIMO ORIGINAL EARPHONES",
    name: "ORAIMO ORIGINAL EARPHONES", category: "9", brand: "3", selling_price: "300", minimum_price: "280", variant_name: "Standard" }} />); });
  expect(screen.getByText(/Filled in from ORAIMO ORIGINAL EARPHONES/)).toBeInTheDocument();
  expect(screen.getByLabelText("Selling price")).toHaveValue(300);
  expect(screen.queryByText("Stock you have now (optional)")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Product name"), { target: { value: "ORAIMO TYPE-C EARPHONES" } });
  await act(async () => { fireEvent.submit(screen.getByRole("button", { name: "Create and receive it" }).closest("form")); });
  const sent = Object.fromEntries(api.mock.calls.find(([path]) => path.includes("create-with-stock"))[1].body);
  expect(sent).toMatchObject({ name: "ORAIMO TYPE-C EARPHONES", category_id: "9", brand_id: "3", selling_price: "300", minimum_price: "280" });
  expect(onSaved).toHaveBeenCalledWith({ product_id: 41, variant_id: 77 });
});
