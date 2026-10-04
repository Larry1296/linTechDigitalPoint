import { render, screen, within, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ShelfDetails } from "./ShelfDetails";
import { loadShelfContents } from "./api";

vi.mock("./api", () => ({ loadShelfContents: vi.fn(), updateShelf: vi.fn() }));

const item = (overrides) => ({ variant_id: 1, product_id: 10, product: "Type-C charger", variant: "25W", sku: "CHG-25W",
  category: "Mobile Accessories", image: null, selling_price: "600.00", quantity: "10.000", reserved: "2.000",
  available: "8.000", retail_value: "6000.00", batches: 2, last_received: "2026-09-24T08:00:00Z", ...overrides });
const contents = (overrides = {}) => ({
  shelf: { code: "LEFTWALL-R01-L2-S1", physical_label: "", display_name: "Level 2 Shelf 1" },
  location: { area: "Left Wall", rack: "Phone Accessories Rack", rack_code: "LEFTWALL-R01", level: 2, position: 1, categories: ["Mobile Accessories"] },
  totals: { items: 1, units: "10.000", available: "8.000", retail_value: "6000.00" },
  show_cost: false, items: [item()], recent_movements: [{ type: "PURCHASE_RECEIPT", product: "Type-C charger — 25W",
    quantity: "6.000", direction: "in", reference: "INV-2", created_at: "2026-09-24T08:00:00Z" }], ...overrides });
beforeEach(() => vi.clearAllMocks());
const open = (shelfId = 7) => render(<MemoryRouter><ShelfDetails shelfId={shelfId} onClose={vi.fn()} onUpdated={vi.fn()} /></MemoryRouter>);

it("opens the shelf with its place in the shop, totals and every item on it", async () => {
  loadShelfContents.mockResolvedValue(contents());
  open();
  const dialog = await screen.findByRole("dialog", { name: "Shelf Level 2 · Shelf 1" });
  expect(within(dialog).getByText("Left Wall · Phone Accessories Rack")).toBeInTheDocument();
  expect(within(dialog).getByText("8 available")).toBeInTheDocument();
  expect(within(dialog).getByText("Type-C charger")).toBeInTheDocument();
  expect(within(dialog).getByText("SKU CHG-25W · Mobile Accessories")).toBeInTheDocument();
  expect(within(dialog).getByText("2 reserved")).toBeInTheDocument();
  expect(within(dialog).getByRole("link", { name: "Adjust count" })).toHaveAttribute("href", "/admin/adjust-stock?variant=1");
  expect(within(dialog).getByRole("link", { name: "View product" })).toHaveAttribute("href", "/admin/product-lookup?product=10&variant=1");
  expect(within(dialog).queryByText("Buying cost")).not.toBeInTheDocument();
  expect(within(dialog).getByText("Received")).toBeInTheDocument();
  expect(within(dialog).queryByText(/Not built yet/)).not.toBeInTheDocument();
});

it("shows buying cost only when allowed and filters a busy shelf", async () => {
  const items = ["Cover", "Charger", "Earphones", "Power bank", "Cable", "Screen guard"].map((name, index) =>
    item({ variant_id: index + 1, product: name, sku: `SKU-${index}`, cost_value: "100.00" }));
  loadShelfContents.mockResolvedValue(contents({ show_cost: true, items,
    totals: { items: 6, units: "60", available: "60", retail_value: "36000", cost_value: "600" } }));
  open();
  expect(await screen.findAllByText("Buying cost")).toHaveLength(7);
  fireEvent.change(screen.getByRole("searchbox", { name: "Find an item on this shelf" }), { target: { value: "power" } });
  expect(document.querySelectorAll(".shelfItem")).toHaveLength(1);
  expect(screen.getByText("Power bank")).toBeInTheDocument();
});

it("shows an empty shelf clearly and a load failure with a retry", async () => {
  loadShelfContents.mockResolvedValueOnce(contents({ items: [], recent_movements: [],
    totals: { items: 0, units: "0", available: "0", retail_value: "0" } }));
  const { unmount } = open();
  expect(await screen.findByText("This shelf is empty.")).toBeInTheDocument();
  unmount();
  loadShelfContents.mockRejectedValueOnce(new Error("Network error"));
  open(8);
  expect(await screen.findByText("Network error")).toBeInTheDocument();
});
