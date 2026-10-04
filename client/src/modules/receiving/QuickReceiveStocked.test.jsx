import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { QuickReceivePage } from "./QuickReceivePage";
import { api } from "../../core/api/client";
import { confirmAction } from "../../core/ui/alerts";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async () => ({ id: 4, receipt_number: "RCV-1" })) }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn() }));
vi.mock("../storefront/components/ProductSearch", () => ({
  ProductSearch: ({ onSelect }) => <button type="button" onClick={() => onSelect({ id: 6, product_name: "Amaya charger", variant_name: "Standard", sku: "AMAYA", available: "2.000" })}>Pick Amaya</button>,
}));
beforeEach(() => vi.clearAllMocks());
const add = async () => { await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add to my stock" })); }); };

it("says an item's existing stock is added to, and records nothing if the user cancels", async () => {
  confirmAction.mockResolvedValue(false);
  render(<MemoryRouter><QuickReceivePage defaultSource="OPENING" /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Pick Amaya" }));
  expect(screen.getByRole("note")).toHaveTextContent("already has 2 of this item");
  expect(screen.getByRole("link", { name: "Adjust stock" })).toHaveAttribute("href", "/admin/adjust-stock?variant=6");
  fireEvent.change(screen.getByLabelText("How many more to add"), { target: { value: "3" } });
  await add();
  expect(confirmAction).toHaveBeenCalledWith(expect.objectContaining({ text: expect.stringContaining("This will make it 5") }));
  expect(api).not.toHaveBeenCalled();
});

it("adds the extra stock once the user confirms", async () => {
  confirmAction.mockResolvedValue(true);
  render(<MemoryRouter><QuickReceivePage defaultSource="OPENING" /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Pick Amaya" }));
  fireEvent.change(screen.getByLabelText("How many more to add"), { target: { value: "3" } });
  await add();
  expect(JSON.parse(api.mock.calls[0][1].body).lines[0]).toMatchObject({ variant_id: 6, received_quantity: "3" });
});
