import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductEditor } from "./ProductEditor";
import { api } from "../../core/api/client";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
afterEach(() => vi.resetAllMocks());
it("edits variant catalogue fields without submitting physical inventory", async () => {
  api.mockResolvedValue({});
  const saved = vi.fn();
  render(
    <ProductEditor
      product={{ id: 1 }}
      variant={{
        id: 2,
        name: "Red",
        sku: "RED",
        barcode: null,
        selling_price: 100,
        minimum_stock: 1,
        target_stock: 10,
        active: true,
        physical: 8,
        available: 7,
      }}
      onSaved={saved}
      onClose={() => {}}
    />,
  );
  expect(screen.queryByLabelText(/physical/i)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Selling price"), {
    target: { value: "150" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  const [url, options] = api.mock.calls[0];
  expect(url).toBe("/api/v1/catalog/variants/2/");
  expect(JSON.parse(options.body)).toEqual({
    name: "Red",
    sku: "RED",
    barcode: null,
    selling_price: "150",
    minimum_stock: 1,
    target_stock: 10,
    active: true,
  });
});
