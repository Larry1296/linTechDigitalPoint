import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { organization: { enabled_modules: ["inventory"] },
  permissions: ["core.view_tobuyitem", "core.add_tobuyitem", "core.change_tobuyitem", "core.delete_tobuyitem", "catalog.view_product"] } }) }));
import { api } from "../../core/api/client";
import { ToBuyPage } from "./ToBuyPage";

const list = {
  items: [{ id: 1, name: "Type-C cables", variant: 7, product: "Type-C cable", quantity: "10", price: "1500.00", note: "", bought: false },
    { id: 2, name: "Printing paper", variant: null, product: null, quantity: "2 reams", price: null, note: "A4", bought: false },
    { id: 3, name: "Glue", variant: null, product: null, quantity: "", price: "100.00", note: "", bought: true }],
  left: 2, left_price: "1500.00", unpriced: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path) => (path.includes("variants/search") ? [{ id: 9, product_name: "Charger", variant_name: "Standard", category: "Phones" }] : list));
});

it("lists what is still to buy with its rough total, and what was ticked as bought apart", async () => {
  render(<ToBuyPage />);
  const left = await screen.findByRole("region", { name: "Still to buy" });
  expect(within(left).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
    expect.stringMatching(/Type-C cables.*Your product: Type-C cable.*10.*1,500/), expect.stringMatching(/Printing paper.*A4.*2 reams/)]);
  expect(within(left).getByText(/2 items · about/)).toHaveTextContent("about KSh 1,500 (1 without a price)");
  expect(within(screen.getByRole("region", { name: "Ticked as bought (1)" })).getByText("Glue")).toBeInTheDocument();
});

it("adds an item linked to one of the products picked from the suggestions", async () => {
  render(<ToBuyPage />);
  const form = await screen.findByRole("form", { name: "Add to the list" });
  fireEvent.change(within(form).getByLabelText("Item"), { target: { value: "Char" } });
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining("variants/search/?q=Char")));
  await waitFor(() => expect(form.querySelector("datalist option")).not.toBeNull());
  fireEvent.change(within(form).getByLabelText("Item"), { target: { value: "Charger" } });
  expect(within(form).getByText(/Linked to your product Charger/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("How many"), { target: { value: "5" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/", expect.objectContaining({ method: "POST" })));
  expect(JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body)).toEqual({ name: "Charger", variant: 9, quantity: "5", price: null, note: "" });
});

it("ticks an item as bought and clears the bought ones", async () => {
  render(<ToBuyPage />);
  fireEvent.click(await screen.findByLabelText("Bought: Printing paper"));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/2/", { method: "PATCH", body: JSON.stringify({ bought: true }) }));
  fireEvent.click(screen.getByRole("button", { name: "Clear these" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/", { method: "DELETE" }));
});
