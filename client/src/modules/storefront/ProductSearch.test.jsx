import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ProductSearch } from "./components/ProductSearch";
import { HomePage } from "./HomePage";
import { ShopPage } from "./ShopPage";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/cart/CartContext", () => ({
  useCart: () => ({ addToCart: vi.fn() }),
}));
const product = {
  id: 12,
  display_name: "Amaya — White — 1m — 6A",
  category: "Charging Cables",
  selling_price: "250.00",
  available: 3,
  images: [],
};
function Location() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output>{location.pathname + location.search}</output>
      <button onClick={() => navigate("/shop?category=7&search=white")}>
        Change URL
      </button>
      <button onClick={() => navigate(-1)}>Back</button>
    </>
  );
}
function setup(element = <ProductSearch />, path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      {element}
      <Location />
    </MemoryRouter>,
  );
}
afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});
async function tick() {
  await act(async () => vi.advanceTimersByTimeAsync(250));
}

it("waits for two trimmed characters and debounces requests; renders exact identities", async () => {
  vi.useFakeTimers();
  api.mockResolvedValue([product]);
  setup();
  const input = screen.getByRole("combobox");
  fireEvent.change(input, { target: { value: " a " } });
  await tick();
  expect(api).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "am" } });
  await act(async () => vi.advanceTimersByTimeAsync(200));
  expect(api).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "ama" } });
  await tick();
  expect(api).toHaveBeenCalledTimes(1);
  expect(api.mock.calls[0][0]).toContain("q=ama");
  expect(screen.getByRole("option")).toHaveTextContent(product.display_name);
  expect(screen.getByRole("option")).toHaveTextContent(product.category);
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByRole("option")).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.getByRole("status")).toHaveTextContent("/products/12");
});

it("Enter submits the query and closes suggestions", () => {
  setup();
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "amaya cable" },
  });
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
  expect(screen.getByRole("status")).toHaveTextContent(
    "/shop?search=amaya+cable",
  );
  expect(screen.getByRole("combobox")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

it("ignores stale results and supports error, empty and dismissal states", async () => {
  vi.useFakeTimers();
  let resolve;
  api
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    )
    .mockResolvedValueOnce([]);
  setup();
  const input = screen.getByRole("combobox");
  fireEvent.change(input, { target: { value: "am" } });
  await tick();
  fireEvent.change(input, { target: { value: "zz" } });
  await tick();
  await act(async () => resolve([product]));
  expect(screen.queryByRole("option")).not.toBeInTheDocument();
  expect(screen.getByText("No available products found.")).toBeInTheDocument();
  api.mockRejectedValueOnce(new Error("Network"));
  fireEvent.change(input, { target: { value: "error" } });
  await tick();
  expect(screen.getByRole("alert")).toBeInTheDocument();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(input).toHaveAttribute("aria-expanded", "false");
  fireEvent.focus(input);
  fireEvent.pointerDown(document.body);
  expect(input).toHaveAttribute("aria-expanded", "false");
  fireEvent.change(input, { target: { value: "" } });
  expect(input).toHaveAttribute("aria-expanded", "false");
});

it("renders every returned homepage product with category links", async () => {
  api.mockResolvedValue({
    store: { name: "Shop" },
    categories: [],
    cyber_services: [],
    category_sections: [
      {
        id: 7,
        name: "Charging Cables",
        products: [product, { ...product, id: 13 }, { ...product, id: 14 }, { ...product, id: 15 }, { ...product, id: 16 }],
      },
    ],
  });
  setup(<HomePage />);
  const section = await screen.findByRole("region", {
    name: "Charging Cables",
  });
  expect(within(section).getAllByRole("article")).toHaveLength(5);
  expect(
    within(section).getByRole("link", { name: "View category →" }),
  ).toHaveAttribute("href", "/shop?category=7");
});

it("initializes and reloads Shop from the URL, preserves category and handles Back", async () => {
  api.mockResolvedValue([]);
  setup(<ShopPage />, "/shop?category=7&search=amaya");
  expect(screen.getByRole("combobox")).toHaveValue("amaya");
  await screen.findByText("No products match your search.");
  expect(api.mock.calls[0][0]).toBe(
    "/api/v1/store/products/?in_stock=true&search=amaya&product__category=7",
  );
  fireEvent.click(screen.getByText("Change URL"));
  expect(screen.getByRole("combobox")).toHaveValue("white");
  await screen.findByText("No products match your search.");
  expect(api.mock.calls.at(-1)[0]).toContain(
    "search=white&product__category=7",
  );
  fireEvent.click(screen.getByText("Back"));
  expect(screen.getByRole("combobox")).toHaveValue("amaya");
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "cable" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  await screen.findByText("No products match your search.");
  expect(screen.getByRole("status")).toHaveTextContent(
    "/shop?category=7&search=cable",
  );
});
