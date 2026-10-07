import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn(), apiBlob: vi.fn(async () => new Blob(["xlsx"])) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["catalog.view_product", "catalog.add_product"] } }) }));
vi.mock("../storefront/components/ProductSearch", () => ({ ProductSearch: () => null }));
vi.mock("../digital-shop/api", () => ({ loadZonesIfUsed: async () => [] }));
import { api, apiBlob } from "../../core/api/client";
import { ProductsPage } from "./ProductsPage";

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path) => (path.includes("category-counts") ? { categories: {}, other: 0 } : path.includes("?page=") ? { results: [], next: null } : []));
  URL.createObjectURL = vi.fn(() => "blob:template");
  URL.revokeObjectURL = vi.fn();
});

it("offers the Excel template on the products page, without opening the import first", async () => {
  render(<MemoryRouter><ProductsPage /></MemoryRouter>);
  expect(await screen.findByText(/Download the sample Excel template in the expected format/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Download Excel template/ }));
  await waitFor(() => expect(apiBlob).toHaveBeenCalledWith("/api/v1/catalog/products/import-template/"));
  fireEvent.click(screen.getByRole("button", { name: "Download template" }));
  await waitFor(() => expect(apiBlob).toHaveBeenCalledTimes(2));
});

it("does not offer the template to people who cannot add products", async () => {
  vi.resetModules();
  vi.doMock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions: ["catalog.view_product"] } }) }));
  const { ProductsPage: Page } = await import("./ProductsPage");
  render(<MemoryRouter><Page /></MemoryRouter>);
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: /Download Excel template/ })).not.toBeInTheDocument();
  expect(screen.queryByText(/sample Excel template/)).not.toBeInTheDocument();
});
