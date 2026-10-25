import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { PosPage } from "./AdminPages";
import { api } from "../../core/api/client";
vi.mock("../../core/auth/AuthContext", () => ({
  useAuth: () => ({ user: { is_superuser: true } }),
}));
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
afterEach(() => vi.resetAllMocks());
it("groups stock and services, disables empty stock and caps cart quantities", async () => {
  const base = {
    product_name: "Cable",
    variant_name: "Red",
    category_name: "Accessories",
    sku: "CB",
    selling_price: 100,
    locations: [],
    product_type: "STOCK_ITEM",
  };
  api.mockResolvedValue([
    { ...base, id: 1, available: 2 },
    { ...base, id: 2, product_name: "Empty", available: 0 },
    {
      ...base,
      id: 3,
      product_name: "Printing",
      product_type: "SERVICE",
      available: 0,
    },
  ]);
  render(
    <MemoryRouter>
      <PosPage />
    </MemoryRouter>,
  );
  await screen.findByRole("heading", { name: "Accessories" });
  expect(screen.getByRole("heading", { name: "Services" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Empty/ })).toBeDisabled();
  const add = screen.getByRole("button", { name: /Cable/ });
  fireEvent.click(add);
  fireEvent.click(add);
  fireEvent.click(add);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^Complete sale/ }));
  const cart = screen
    .getByRole("heading", { name: "Current sale" })
    .closest("form");
  const quantity = within(cart).getAllByRole("spinbutton")[0];
  expect(quantity).toHaveValue(2);
  fireEvent.change(quantity, { target: { value: "99" } });
  expect(quantity).toHaveValue(2);
});
