import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { StockQuickSearch } from "./StockQuickSearch";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));

const row = (id, name, available, extra = {}) => ({ id, product_id: id, product_name: name, variant_name: "Standard", category_name: "Chargers",
  product_type: "STOCK_ITEM", selling_price: "300.00", available, locations: available ? [{ shelf_code: "LEFTWALL-R01-L01-S01", shelf_name: "Left wall, level 1" }] : [], ...extra });

it("shows every matching product with its price, stock and shelf, what is in stock first", async () => {
  api.mockResolvedValue([row(1, "ORIGINAL CAR CHARGER", 0), row(2, "AMAYA 10W MICROUSB CHARGER", 2, { variant_name: "10W" }),
    row(3, "WINDOWS INSTALL", 0, { product_type: "SERVICE" })]);
  render(<MemoryRouter><StockQuickSearch /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Search stock"), { target: { value: "mobile charger" } });
  expect(await screen.findByText("2 products found · 1 in stock")).toBeInTheDocument();
  expect(api).toHaveBeenLastCalledWith("/api/v1/catalog/products/search-suggestions/?q=mobile%20charger");
  const items = screen.getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("AMAYA 10W MICROUSB CHARGER — 10W");
  expect(items[0]).toHaveTextContent("Left wall, level 1");
  expect(items[0]).toHaveTextContent("2 in stock");
  expect(items[1]).toHaveTextContent("Out of stock");
  expect(screen.queryByText(/WINDOWS INSTALL/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Clear search"));
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

it("comes with the cursor in the box when / was pressed on another page", () => {
  render(<MemoryRouter initialEntries={[{ pathname: "/admin/dashboard", state: { focusStockSearch: true } }]}><StockQuickSearch /></MemoryRouter>);
  expect(screen.getByLabelText("Search stock")).toHaveFocus();
});
