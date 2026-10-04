vi.mock("../../components/PrivateImage", () => ({ PrivateImage: props => <img {...props} /> }));
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ShopPage } from "./ShopPage";
import { HomePage } from "./HomePage";
import { ProductPage } from "./ProductPage";
import { ProductCard } from "./components/ProductCard";
import { CartPage } from "./CartPage";
import { CheckoutPage } from "../customer/CheckoutPage";
import { OrdersPage, OrderDetailPage } from "../customer/AccountPage";
import { api } from "../../core/api/client";
import amayaImage from "../../assets/images/stock/Amaya Normal Charging USB Cable.png";
afterEach(() => vi.unstubAllGlobals());

it.each(["/shop?category=7&search=Amaya", "/#categories"])(
  "returns to the same listing and scroll position from %s",
  async (path) => {
    sessionStorage.clear();
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    vi.stubGlobal("scrollY", 850);
    api.mockImplementation(async (url) => {
      if (url.includes("/store/home/"))
        return {
          store: { name: "Shop" },
          categories: [],
          category_sections: [{ id: 7, name: "Charging Cables", products: [variants[0]] }],
          cyber_services: [],
        };
      if (url.includes("/products/?")) return [variants[0]];
      return { ...variants[0], variants };
    });
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/shop" element={<ShopPage />} />
          <Route path="/products/:id" element={<ProductPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(
      await screen.findByRole("link", { name: "Choose an option" }),
    );
    await screen.findByRole("heading", { name: variants[0].display_name });
    scrollTo.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "← Back" }));
    await screen.findByRole("link", { name: "Choose an option" });
    await waitFor(() =>
      expect(scrollTo).toHaveBeenCalledWith({ top: 850, behavior: "instant" }),
    );
    if (path.startsWith("/shop")) {
      expect(screen.getByLabelText("Search products")).toHaveValue("Amaya");
      expect(api).toHaveBeenLastCalledWith(
        "/api/v1/store/products/?in_stock=true&search=Amaya&product__category=7",
      );
    }
  },
);
const mocks = vi.hoisted(() => ({
  addToCart: vi.fn(),
  refreshCart: vi.fn(),
  cart: null,
}));
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/cart/CartContext", () => ({
  useCart: () => ({ ...mocks, changeQuantity: vi.fn(), removeItem: vi.fn() }),
}));
vi.mock("../../core/auth/AuthContext", () => ({
  useAuth: () => ({ user: { username: "buyer" } }),
}));
const variants = ["Type-B (Micro-USB)", "Type-C"].map((connector, index) => ({
  id: index + 1,
  variant_id: index + 1,
  product_id: 1,
  product_name: "Amaya USB Charging Cable",
  variant_name: `AM-M01 — ${connector} — White — 1.2m — 3.1A`,
  display_name: `Amaya USB Charging Cable — AM-M01 — ${connector} — White — 1.2m — 3.1A`,
  sku: `CABLE-${index}`,
  selling_price: "250.00",
  available: "5",
  variant_count: 2,
  category: "Charging Cables",
  online_orderable: true,
  images: [{ url: `/media/type-${index}.webp`, alt: connector }],
  attributes: [{ name: "Connector type", value: connector }],
}));
const fallbackCable = {
  ...variants[0],
  sku: "AMAYA-AM-M01-MICRO-B-WHT-1M2",
  images: [],
};
const fallbackAlt =
  "Amaya AM-M01 Type-B Micro-USB white 1.2m 3.1A charging cable";

it.each(["card", "details", "cart", "checkout"])(
  "shows the exact SKU photo and complete identity in %s",
  async (view) => {
    const typeC = { ...variants[1], images: [] };
    mocks.cart.items = [fallbackCable, typeC].map((v) => ({
      ...v,
      quantity: "1",
      line_total: "250.00",
    }));
    if (view === "details") {
      api.mockResolvedValue({
        ...fallbackCable,
        variants: [fallbackCable, typeC],
      });
      route(<ProductPage />);
    } else if (view === "card") {
      route(
        <>
          <ProductCard product={fallbackCable} />
          <ProductCard product={typeC} />
        </>,
      );
    } else {
      route(view === "cart" ? <CartPage /> : <CheckoutPage />);
    }
    expect(
      await screen.findByRole("img", { name: fallbackAlt }),
    ).toHaveAttribute("src", amayaImage);
    expect(
      screen.getAllByText((text) => text.includes(fallbackCable.display_name))
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByRole("img")).toHaveLength(1);
    if (view === "details") {
      fireEvent.change(screen.getByLabelText("Choose a variant"), {
        target: { value: typeC.id },
      });
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: typeC.display_name }),
      ).toBeInTheDocument();
    }
  },
);

it("prefers a backend image over the local SKU fallback", () => {
  route(
    <ProductCard
      product={{
        ...fallbackCable,
        images: [{ url: "/media/actual-cable.webp" }],
      }}
    />,
  );
  expect(screen.getByRole("img", { name: fallbackAlt })).toHaveAttribute(
    "src",
    "/media/actual-cable.webp",
  );
});
beforeEach(() => {
  vi.clearAllMocks();
  mocks.addToCart.mockResolvedValue({});
  mocks.refreshCart.mockResolvedValue({});
  mocks.cart = {
    items: variants.map((v) => ({
      ...v,
      quantity: "1",
      line_total: "250.00",
      unit_price: "250.00",
    })),
    total: "500.00",
  };
});
function route(element, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={element} />
      </Routes>
    </MemoryRouter>,
  );
}
it("product/search cards identify each connector and link to variant choice", () => {
  route(
    <>
      {variants.map((product) => (
        <ProductCard
          key={product.id}
          product={product}
          onAdd={mocks.addToCart}
        />
      ))}
    </>,
  );
  for (const variant of variants) {
    expect(
      screen.getByRole("heading", { name: variant.display_name }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: variant.display_name }),
    ).toHaveAttribute("src", variant.images[0].url);
  }
  expect(screen.getAllByRole("link", { name: "Choose an option" })).toHaveLength(
    2,
  );
  expect(
    screen.queryByRole("button", { name: "Add to cart" }),
  ).not.toBeInTheDocument();
});
it.each(variants)(
  "requires explicit selection and adds the selected variant $variant_id",
  async (variant) => {
    api.mockResolvedValue({ ...variants[0], variants });
    render(
      <MemoryRouter initialEntries={["/products/1"]}>
        <Routes>
          <Route path="/products/:id" element={<ProductPage />} />
          <Route path="/cart" element={<p>Cart destination</p>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("button", {
        name: "Choose an option to add to cart",
      }),
    ).toBeDisabled();
    expect(mocks.addToCart).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Choose a variant"), {
      target: { value: variant.id },
    });
    expect(
      screen.getByRole("heading", { name: variant.display_name }),
    ).toBeInTheDocument();
    expect(screen.getByText(variant.attributes[0].value)).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: variant.display_name }),
    ).toHaveAttribute("src", variant.images[0].url);
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    await screen.findByText("Cart destination");
    expect(mocks.addToCart).toHaveBeenCalledWith(variant.variant_id);
  },
);
it.each([CartPage, CheckoutPage])(
  "cart and checkout show full identities",
  async (Page) => {
    route(<Page />);
    for (const variant of variants)
      expect(
        screen.getByRole("img", { name: variant.display_name }),
      ).toHaveAttribute("src", variant.images[0].url);
    for (const variant of variants)
      expect(
        (
          await screen.findAllByText((text) =>
            text.includes(variant.display_name),
          )
        ).length,
      ).toBeGreaterThan(0);
  },
);
it.each([OrdersPage, OrderDetailPage])(
  "order history and printable receipt retain both identities",
  async (Page) => {
    const order = {
      id: 1,
      number: "ORDER-1",
      total: "500.00",
      items: mocks.cart.items,
      status: "PAID",
    };
    api.mockResolvedValue(Page === OrdersPage ? [order] : order);
    route(<Page />);
    for (const variant of variants)
      expect(
        (
          await screen.findAllByText((text) =>
            text.includes(variant.display_name),
          )
        ).length,
      ).toBeGreaterThan(0);
    if (Page === OrderDetailPage)
      for (const variant of variants)
        expect(
          screen.getByRole("img", { name: variant.display_name }),
        ).toHaveAttribute("src", variant.images[0].url);
    if (Page === OrderDetailPage)
      expect(
        screen.getByRole("button", { name: "Print order / receipt" }),
      ).toBeInTheDocument();
  },
);
