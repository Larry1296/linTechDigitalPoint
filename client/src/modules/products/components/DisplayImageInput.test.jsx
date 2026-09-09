import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DisplayImageInput } from "./DisplayImageInput";
import { ProductPhotos } from "../ProductPhotos";
import { api } from "../../../core/api/client";
vi.mock("../../../core/api/client", () => ({ api: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); URL.createObjectURL = vi.fn(() => "blob:preview"); URL.revokeObjectURL = vi.fn(); });
function Input() { const [file, setFile] = useState(null); return <DisplayImageInput file={file} onChange={setFile} required />; }
it("offers storage and camera selection with a removable preview", () => {
  const { unmount } = render(<Input />);
  expect(screen.getByLabelText("Take photo")).toHaveAttribute("capture", "environment");
  const file = new File(["photo"], "type-b.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText("Take photo"), { target: { files: [file] } });
  expect(screen.getByAltText("Product display image preview")).toHaveAttribute("src", "blob:preview");
  fireEvent.click(screen.getByRole("button", { name: "Remove selected photo" }));
  expect(screen.queryByAltText("Product display image preview")).not.toBeInTheDocument();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  unmount();
});
it("rejects non-images before saving", () => {
  render(<Input />);
  fireEvent.change(screen.getByLabelText("Upload from storage"), { target: { files: [new File(["text"], "receipt.txt", { type: "text/plain" })] } });
  expect(screen.getByRole("alert")).toHaveTextContent("JPEG, PNG or WebP");
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
const product = { id: 1, name: "Amaya cable", selectedVariantId: 2, images: [], variants: [{ id: 2, name: "Type-B", sku: "TYPE-B", images: [] }] };
it("uploads an existing variant's dedicated photo without stock fields", async () => {
  api.mockResolvedValue({}); const saved = vi.fn();
  render(<ProductPhotos product={product} onSaved={saved} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Upload from storage"), { target: { files: [new File(["photo"], "type-b.png", { type: "image/png" })] } });
  fireEvent.click(screen.getByRole("button", { name: "Save display image" }));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  const [url, request] = api.mock.calls[0];
  expect(url).toBe("/api/v1/catalog/products/1/display-image/");
  expect(request.body.get("variant_id")).toBe("2");
  expect(request.body.get("display_image")).toBeInstanceOf(File);
  expect(request.body.has("selling_price")).toBe(false);
  expect(request.body.has("received_quantity")).toBe(false);
});
it("allows another variant to explicitly reuse the main photo", async () => {
  api.mockResolvedValue({});
  render(<ProductPhotos product={product} onSaved={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Create another variant" }));
  fireEvent.change(screen.getByLabelText("Variant name"), { target: { value: "Type-C" } });
  fireEvent.change(screen.getByLabelText("SKU"), { target: { value: "TYPE-C" } });
  fireEvent.change(screen.getByLabelText("Selling price"), { target: { value: "300" } });
  fireEvent.click(screen.getByLabelText(/Reuse the product's main image/));
  fireEvent.click(screen.getByRole("button", { name: "Create variant" }));
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect(api.mock.calls[0][0]).toBe("/api/v1/catalog/products/1/variants/");
  expect(api.mock.calls[0][1].body.get("use_product_image")).toBe("true");
});
