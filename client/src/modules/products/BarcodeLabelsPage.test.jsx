import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../core/api/client";
import { BarcodeLabelsPage } from "./BarcodeLabelsPage";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
const rows = [{ id: 1, product_name: "ITEL A16 SOFT COVER", variant_name: "SOFT", sku: "ITL-A16-SOFT", barcode: null, selling_price: "300", category_name: "Covers" },
  { id: 2, product_name: "Charger", variant_name: "Standard", sku: "CH-1", barcode: "6161101234567", selling_price: "500", category_name: "Power" }];
beforeEach(() => {
  vi.clearAllMocks();
  window.print = vi.fn();
  api.mockImplementation(async (path) => (path === "/api/v1/catalog/barcodes/labels/"
    ? { labels: [{ ...rows[0], barcode: "2100000000014" }] } : rows));
});

it("prints labels, giving products without a barcode the shop's own", async () => {
  render(<BarcodeLabelsPage />);
  expect(await screen.findByText(/of 2 products have no barcode yet/)).toBeInTheDocument();
  expect(screen.queryByText("Charger")).not.toBeInTheDocument(); // it has a barcode: hidden while "only without" is ticked
  fireEvent.click(screen.getByLabelText(/Choose all shown/));
  fireEvent.change(screen.getByLabelText("Labels for ITEL A16 SOFT COVER · SOFT"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Print 3 labels" }));
  await waitFor(() => expect(window.print).toHaveBeenCalled());
  expect(JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/catalog/barcodes/labels/")[1].body)).toEqual({ variant_ids: [1] });
  expect(document.querySelectorAll(".barcodeLabel")).toHaveLength(3);
});
