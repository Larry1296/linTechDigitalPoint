import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async () => ({})) }));
import { api } from "../../core/api/client";
import { ProductPhotos } from "./ProductPhotos";

const product = { id: 5, name: "USB cable", images: [], variants: [{ id: 9, name: "Type-C", sku: "USB-C" }] };

it("keeps photos optional: nothing asks for one, and a new type is added without a photo", async () => {
  const onSaved = vi.fn();
  render(<ProductPhotos embedded product={product} canCreateVariant onSaved={onSaved} />);
  expect(screen.getByText("Product photo (optional)")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save display image" })).toBeDisabled();  // nothing chosen, nothing to save
  fireEvent.click(screen.getByRole("button", { name: "Add another type" }));
  fireEvent.change(screen.getByLabelText("Variant name"), { target: { value: "Type-B" } });
  fireEvent.change(screen.getByLabelText("SKU"), { target: { value: "USB-B" } });
  fireEvent.change(screen.getByLabelText("Selling price"), { target: { value: "300" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add type" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/catalog/products/5/variants/", expect.objectContaining({ method: "POST" }));
  expect(api.mock.calls[0][1].body.get("display_image")).toBeNull();
  expect(onSaved).toHaveBeenCalled();
});
