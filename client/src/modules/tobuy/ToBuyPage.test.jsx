import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { organization: { enabled_modules: ["inventory"] },
  permissions: ["core.view_tobuyitem", "core.add_tobuyitem", "core.change_tobuyitem", "core.delete_tobuyitem", "catalog.view_product"] } }) }));
import { api } from "../../core/api/client";
import { ToBuyPage } from "./ToBuyPage";

const item = (id, name, count, unitPrice, extra = {}) => ({ id, name, variant: null, product: null, count: String(count), unit: "", note: "", bought: false,
  unit_price: unitPrice == null ? null : String(unitPrice), total: unitPrice == null ? null : String(count * unitPrice), ...extra });
const list = {
  items: [item(1, "Type-C cables", 10, 150, { variant: 7, product: "Type-C cable", unit: "pcs" }), item(2, "Printing paper", 2, null, { unit: "reams", note: "A4" }),
    item(4, "Screen protectors", 20, 40), item(3, "Glue", 1, 100, { bought: true })],
  left: 3, left_total: "2300.00", unpriced: 1, bought: 1, bought_total: "100.00", all_total: "2400.00",
};

beforeEach(() => {
  vi.clearAllMocks();
  try { localStorage.clear(); } catch { /* none */ }
  api.mockImplementation(async (path) => (path.includes("variants/search") ? [{ id: 9, product_name: "Charger", variant_name: "Standard", category: "Phones" }] : list));
});

it("works out each line's total and the money to carry for what is still to buy", async () => {
  render(<ToBuyPage />);
  const left = await screen.findByRole("region", { name: "Still to buy" });
  const rows = within(left).getAllByRole("listitem");
  expect(within(rows[0]).getByText("KSh 1,500")).toBeInTheDocument();
  expect(within(rows[1]).getByText("No price")).toBeInTheDocument();
  expect(screen.getByText("Money to carry").nextSibling).toHaveTextContent(/KSh 2,300.*1 without a price not counted/);
  expect(screen.getByText("Spent so far").nextSibling).toHaveTextContent("KSh 100");
  expect(within(left).getByText("Total to carry").nextSibling).toHaveTextContent("KSh 2,300");
});

it("changes how many on a line and every total follows as you type, then saves it", async () => {
  render(<ToBuyPage />);
  const howMany = await screen.findByLabelText("How many Type-C cables");
  fireEvent.change(howMany, { target: { value: "12" } });
  expect(screen.getByText("Money to carry").nextSibling).toHaveTextContent("KSh 2,600");
  fireEvent.blur(howMany);
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/1/", { method: "PATCH", body: JSON.stringify({ count: "12", unit_price: "150" }) }));
});

it("says whether the money you have is enough", async () => {
  render(<ToBuyPage />);
  const have = await screen.findByLabelText("Money you have");
  fireEvent.change(have, { target: { value: "2000" } });
  expect(screen.getByRole("status")).toHaveTextContent("Short by KSh 300, not counting 1 without a price");
  fireEvent.change(have, { target: { value: "3000" } });
  expect(screen.getByRole("status")).toHaveTextContent("Enough: KSh 700 left over");
});

it("adds an item linked to a product, its total worked out from how many and the price each", async () => {
  render(<ToBuyPage />);
  const form = await screen.findByRole("form", { name: "Add to the list" });
  fireEvent.change(within(form).getByLabelText("Item"), { target: { value: "Char" } });
  await waitFor(() => expect(form.querySelector("datalist option")).not.toBeNull());
  fireEvent.change(within(form).getByLabelText("Item"), { target: { value: "Charger" } });
  expect(within(form).getByText(/Linked to your product Charger/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("How many"), { target: { value: "5" } });
  fireEvent.change(within(form).getByLabelText(/Price each/), { target: { value: "350" } });
  expect(within(form).getByText("Total").nextSibling).toHaveTextContent("KSh 1,750");
  fireEvent.click(within(form).getByRole("button", { name: "Add" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/", expect.objectContaining({ method: "POST" })));
  expect(JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body)).toEqual({ name: "Charger", variant: 9, count: "5", unit: "", unit_price: "350", note: "" });
});

it("ticks an item as bought and clears the bought ones", async () => {
  render(<ToBuyPage />);
  fireEvent.click(await screen.findByLabelText("Bought: Printing paper"));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/2/", { method: "PATCH", body: JSON.stringify({ bought: true }) }));
  fireEvent.click(screen.getByRole("button", { name: "Clear these" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/", { method: "DELETE" }));
});

it("edits everything on a line, a bought one too, and removes any line", async () => {
  render(<ToBuyPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit Printing paper" }));
  const form = screen.getByRole("form", { name: "Change Printing paper" });
  fireEvent.change(within(form).getByLabelText("Item"), { target: { value: "Printing paper A3" } });
  fireEvent.change(within(form).getByLabelText("Unit"), { target: { value: "packets" } });
  fireEvent.change(within(form).getByLabelText(/Price each/), { target: { value: "500" } });
  fireEvent.change(within(form).getByLabelText("Note"), { target: { value: "" } });
  expect(within(form).getByText("Total").nextSibling).toHaveTextContent("KSh 1,000");
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/2/", { method: "PATCH",
    body: JSON.stringify({ name: "Printing paper A3", variant: null, count: "2", unit: "packets", unit_price: "500", note: "" }) }));
  await waitFor(() => expect(screen.queryByRole("form", { name: "Change Printing paper" })).toBeNull());

  fireEvent.click(screen.getByRole("button", { name: "Edit Glue" }));
  fireEvent.click(within(screen.getByRole("form", { name: "Change Glue" })).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("form", { name: "Change Glue" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Remove Glue" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/to-buy/3/", { method: "DELETE" }));
});
