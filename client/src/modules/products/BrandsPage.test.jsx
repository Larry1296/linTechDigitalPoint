import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BrandsPage } from "./BrandsPage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { is_superuser: true, permissions: [] } }) }));
beforeEach(() => vi.clearAllMocks());

it("adds a brand and explains why a brand in use cannot be deleted", async () => {
  let brands = [{ id: 1, name: "Tecno", active: true, product_count: 3 }];
  api.mockImplementation(async (path, options = {}) => {
    if (options.method === "POST") { const brand = { id: 2, name: "Oraimo", active: true, product_count: 0 }; brands = [...brands, brand]; return brand; }
    if (options.method === "DELETE") throw new Error("Tecno is used by 3 products. Change those products' brand first, or edit this brand and untick Active to hide it.");
    return brands;
  });
  render(<BrandsPage />);
  fireEvent.change(await screen.findByLabelText("Brand name"), { target: { value: "Oraimo" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add brand" })); });
  expect(screen.getByText("Oraimo added.")).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "Oraimo" })).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete Tecno" })); });
  expect(screen.getByRole("alert")).toHaveTextContent("Tecno is used by 3 products.");
});
