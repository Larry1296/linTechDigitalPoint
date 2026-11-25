import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PosPage } from "./PosPage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/ui/alerts", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 1, permissions: ["commerce.add_sale", "catalog.change_productvariant"] } }) }));
// The search box picks the product an unknown barcode belongs to.
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: ({ label, onSelect }) => (label === "Product with this barcode"
  ? <button type="button" onClick={() => onSelect({ id: 2, product_name: "Earphones", barcode: null })}>Pick Earphones</button> : null) }));
// The camera: a button stands in for holding a barcode up to it.
vi.mock("../../core/scanner/CameraScanner", () => ({ beep: vi.fn(),
  CameraScanner: ({ onCode }) => <div>
    <button type="button" onClick={() => onCode("6161101234567")}>Show charger</button>
    <button type="button" onClick={() => onCode("6009876543210")}>Show unknown</button>
  </div> }));

const item = (id, name, barcode) => ({ id, product_name: name, variant_name: "Standard", sku: `S${id}`, barcode, selling_price: "300.00",
  available: "10", product_type: "STOCK_ITEM", category_name: "Power" });
let linked;
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  linked = null;
  api.mockImplementation(async (path) => {
    if (path.startsWith("/api/v1/catalog/barcodes/link/2/")) { linked = "6009876543210"; return {}; }
    if (path.startsWith("/api/v1/commerce/pos/catalog/")) return [item(1, "Charger", "6161101234567"), item(2, "Earphones", linked)];
    if (path === "/api/v1/commerce/pos/checkouts/") return { checkouts: [] };
    return {};
  });
});

it("adds what the camera reads to the sale and remembers the camera for the next time", async () => {
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Scan with camera" }));
  expect(localStorage.getItem("pos-camera")).toBe("on");
  fireEvent.click(screen.getByRole("button", { name: "Show charger" }));
  expect(await screen.findByText("Added Charger")).toBeInTheDocument();
  expect(screen.getByText(/1 item/)).toBeInTheDocument();
});

it("saves an unknown barcode on the product picked, then sells it", async () => {
  localStorage.setItem("pos-camera", "on");
  render(<MemoryRouter><PosPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Show unknown" }));
  expect(await screen.findByText("No product has the barcode 6009876543210")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Pick Earphones" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/catalog/barcodes/link/2/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText("Added Earphones")).toBeInTheDocument();
});
