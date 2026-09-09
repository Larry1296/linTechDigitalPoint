import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ProductPage } from "./ProductPage";
import { ProductCard } from "./components/ProductCard";
import { CartPage } from "./CartPage";
import { CheckoutPage } from "../customer/CheckoutPage";
import { OrdersPage, OrderDetailPage } from "../customer/AccountPage";
import { api } from "../../core/api/client";
const mocks = vi.hoisted(() => ({ addToCart: vi.fn(), refreshCart: vi.fn(), cart: null }));
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/cart/CartContext", () => ({ useCart: () => ({ ...mocks, changeQuantity: vi.fn(), removeItem: vi.fn() }) }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { username: "buyer" } }) }));
const variants = ["Type-B (Micro-USB)", "Type-C"].map((connector, index) => ({
  id: index + 1, variant_id: index + 1, product_id: 1,
  product_name: "Amaya USB Charging Cable", variant_name: `AM-M01 — ${connector} — White — 1.2m — 3.1A`,
  display_name: `Amaya USB Charging Cable — AM-M01 — ${connector} — White — 1.2m — 3.1A`,
  sku: `CABLE-${index}`, selling_price: "250.00", available: "5", variant_count: 2,
  category: "Charging Cables", online_orderable: true, images: [{ url: `/media/type-${index}.webp`, alt: connector }],
  attributes: [{ name: "Connector type", value: connector }],
}));
beforeEach(() => {
  vi.clearAllMocks();
  mocks.addToCart.mockResolvedValue({}); mocks.refreshCart.mockResolvedValue({});
  mocks.cart = { items: variants.map((v) => ({ ...v, quantity: "1", line_total: "250.00", unit_price: "250.00" })), total: "500.00" };
});
function route(element, path="/") {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path="*" element={element} /></Routes></MemoryRouter>);
}
it("product/search cards identify each connector and link to variant choice", () => {
  route(<>{variants.map((product) => <ProductCard key={product.id} product={product} onAdd={mocks.addToCart} />)}</>);
  for (const variant of variants) {
    expect(screen.getByRole("heading", { name: variant.display_name })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: variant.display_name })).toHaveAttribute("src", variant.images[0].url);
  }
  expect(screen.getAllByRole("link", { name: "Choose variant" })).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "Add to cart" })).not.toBeInTheDocument();
});
it.each(variants)("requires explicit selection and adds the selected variant $variant_id", async (variant) => {
  api.mockResolvedValue({ ...variants[0], variants });
  render(<MemoryRouter initialEntries={["/products/1"]}><Routes><Route path="/products/:id" element={<ProductPage />} /><Route path="/cart" element={<p>Cart destination</p>} /></Routes></MemoryRouter>);
  expect(await screen.findByRole("button", { name: "Choose a variant to add to cart" })).toBeDisabled();
  expect(mocks.addToCart).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Choose a variant"), { target: { value: variant.id } });
  expect(screen.getByRole("heading", { name: variant.display_name })).toBeInTheDocument();
  expect(screen.getByText(variant.attributes[0].value)).toBeInTheDocument();
  expect(screen.getByRole("img", { name: variant.display_name })).toHaveAttribute("src", variant.images[0].url);
  fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
  await screen.findByText("Cart destination");
  expect(mocks.addToCart).toHaveBeenCalledWith(variant.variant_id);
});
it.each([CartPage, CheckoutPage])("cart and checkout show full identities", async (Page) => {
  route(<Page />);
  for (const variant of variants) expect(screen.getByRole("img", { name: variant.display_name })).toHaveAttribute("src", variant.images[0].url);
  for (const variant of variants) expect((await screen.findAllByText((text) => text.includes(variant.display_name))).length).toBeGreaterThan(0);
});
it.each([OrdersPage, OrderDetailPage])("order history and printable receipt retain both identities", async (Page) => {
  const order = { id: 1, number: "ORDER-1", total: "500.00", items: mocks.cart.items, status: "PAID" };
  api.mockResolvedValue(Page === OrdersPage ? [order] : order);
  route(<Page />);
  for (const variant of variants) expect((await screen.findAllByText((text) => text.includes(variant.display_name))).length).toBeGreaterThan(0);
  if (Page === OrderDetailPage) for (const variant of variants) expect(screen.getByRole("img", { name: variant.display_name })).toHaveAttribute("src", variant.images[0].url);
  if (Page === OrderDetailPage) expect(screen.getByRole("button", { name: "Print order / receipt" })).toBeInTheDocument();
});
