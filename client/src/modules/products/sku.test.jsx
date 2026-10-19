import { MemoryRouter } from "react-router-dom";
import { ProductsPage } from "./ProductsPage";
import { ReceivePage } from "../receiving/ReceivePage";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { suggestProductSku } from "./sku";
import { ProductSkuField } from "./components/ProductSkuField";
import { ProductForm } from "./ProductForm";
import { api } from "../../core/api/client";
vi.mock("../../core/api/client", () => ({ api: vi.fn(), apiUrl: (path) => path }));
const zones = [
  {
    id: 1,
    active: true,
    name: "Right",
    stacks: [
      {
        id: 2,
        active: true,
        code: "RIGHT-R01",
        display_name: "Right rack",
        levels: [
          {
            id: 3,
            active: true,
            level_number: 1,
            shelves: [
              {
                id: 4,
                active: true,
                code: "RIGHT-R01-L01-S02",
                display_name: "Compartment 2",
              },
            ],
          },
        ],
      },
    ],
  },
];
beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:photo");
  URL.revokeObjectURL = vi.fn();
  api.mockImplementation(async (path) =>
    path.includes("categories") ? [{ id: 1, name: "Covers" }] : [],
  );
});
describe("searchable SKU suggestions", () => {
  it("builds BRAND-CODE-VARIANT without repeating words or the shelf position", () => {
    expect(suggestProductSku({ productName: "Original Normal Full Charger", brandName: "Oraimo", variantName: "Standard" })).toBe("ORAIMO-ONFC");
    expect(suggestProductSku({ productName: "Oraimo Original Normal Full Charger", brandName: "Oraimo", variantName: "Standard",
      compartmentCode: "LEFTWALL-R01-L01-S01" })).toBe("ORAIMO-ONFC");
    expect(suggestProductSku({ productName: "Power Bank 20000", brandName: "Oraimo", variantName: "Black" })).toBe("ORAIMO-PB-20000-BLACK");
    // The brand, name and variant all say EVERADY 2AA: it appears once.
    expect(suggestProductSku({ productName: "EVERADY 2AA", brandName: "EVERADY", variantName: "EVERADY-2AA" })).toBe("EVERADY-2AA");
    expect(suggestProductSku({ productName: "C-C HEAD(45W)" })).toBe("CCH-45W");
  });
  it("works without a brand, normalises punctuation and keeps one-word names readable", () => {
    expect(suggestProductSku({ productName: "Smartphone Cover", variantName: "Samsung A15 / Black" }))
      .toBe("SC-SAMSUNG-A15-BLACK");
    expect(suggestProductSku({ productName: "  Café & cable! " })).toBe("CC");
    expect(suggestProductSku({ productName: "Router", brandName: "TP-Link" })).toBe("TP-LINK-ROUTER");
    expect(suggestProductSku({ productName: "" })).toBe("");
  });
  it("stays within the database's 64-character limit", () => {
    const result = suggestProductSku({
      productName: "Very long name ".repeat(20),
      brandName: "A brand with a very long name indeed",
      variantName: "Blue with extra long variant description",
    });
    expect(result.length).toBeLessThanOrEqual(64);
    expect(result.startsWith("A-BRAND-WITH")).toBe(true);
  });
  it("marks service codes", () => {
    expect(
      suggestProductSku({
        productName: "Printing",
        productType: "SERVICE",
        compartmentCode: "RIGHT-R01-L01-S02",
      }),
    ).toBe("PRINTING-SERVICE");
  });
  it("updates suggestions while preserving manual overrides until reset", () => {
    const { rerender } = render(
      <ProductSkuField productName="Cover" />,
    );
    expect(screen.getByLabelText("SKU")).toHaveValue("COVER");
    rerender(
      <ProductSkuField
        productName="Cover"
        variantName="Blue"
      />,
    );
    expect(screen.getByLabelText("SKU")).toHaveValue(
      "COVER-BLUE",
    );
    fireEvent.change(screen.getByLabelText("SKU"), {
      target: { value: "CUSTOM-001" },
    });
    rerender(
      <ProductSkuField productName="Padlock" />,
    );
    expect(screen.getByLabelText("SKU")).toHaveValue("CUSTOM-001");
    fireEvent.click(screen.getByRole("button", { name: "Use suggested SKU" }));
    expect(screen.getByLabelText("SKU")).toHaveValue(
      "PADLOCK",
    );
  });
  it("submits the suggested SKU with the selected exact compartment", async () => {
    const saved = vi.fn();
    render(<ProductForm zones={zones} preferredShelf={4} onSaved={saved} />);
    await screen.findByRole("option", { name: /Covers/ });
    fireEvent.change(screen.getByLabelText(/Product category/), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Product name"), {
      target: { value: "Smartphone Cover" },
    });
    fireEvent.change(screen.getByLabelText("Variant", { exact: true }), {
      target: { value: "Black" },
    });
    fireEvent.change(screen.getByLabelText("Selling price"), {
      target: { value: "200" },
    });
    expect(screen.getByLabelText("SKU")).toHaveValue(
      "SC-BLACK",
    );
    fireEvent.change(screen.getByLabelText("Upload from storage"), {
      target: {
        files: [new File(["photo"], "type-b.png", { type: "image/png" })],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Product" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    const request = api.mock.calls.find(([path]) =>
      path.includes("create-with-stock"),
    );
    expect(Object.fromEntries(request[1].body)).toEqual(
      expect.objectContaining({
        sku: "SC-BLACK",
        preferred_shelf_id: "4",
      }),
    );
  });
});

it("searches Products on the server and selects the exact variant", async () => {
  const product = {
    id: 1,
    name: "Cover",
    variants: [{ id: 2, name: "Black", sku: "COVER-RIGHT-R01" }],
    locations: [],
  };
  api.mockImplementation(async (path) =>
    path.includes("locations")
      ? zones
      : path.includes("search-suggestions")
        ? [
            {
              id: 2,
              product_id: 1,
              product_name: "Cover",
              variant_name: "Black",
              sku: "COVER-RIGHT-R01",
            },
          ]
        : path.includes("?page=")
          ? { results: [product], next: null }
          : product,
  );
  render(
    <MemoryRouter>
      <ProductsPage />
    </MemoryRouter>,
  );
  // The search reaches every product, whichever category is open.
  fireEvent.change(await screen.findByRole("combobox"), {
    target: { value: "RIGHT-R01" },
  });
  fireEvent.click(await screen.findByRole("option"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/api/v1/catalog/products/1/"),
  );
  // The search opens the product's own page with the chosen variant.
  expect(await screen.findByRole("heading", { level: 1, name: "Cover" })).toBeInTheDocument();
  expect(screen.getByRole("rowheader", { name: /Black/ }).closest("tr")).toHaveClass("selectedRow");
});

it("opens on the top-level categories and drills down through sub-categories to the products", async () => {
  const product = { id: 5, name: "50W Rechargeable Bulbs", active: true, product_type: "STOCK_ITEM", category: 11, category_name: "Electrical",
    brand_name: "DPLight", description: "Rechargeable 50W bulb", locations: [],
    variants: [{ id: 6, name: "50W-Bulb", sku: "DPLIGHT-5RB-50W-BULB", selling_price: "900.00", minimum_price: "800.00",
      available: "1.000", physical: "1.000", reserved: "0", minimum_stock: "1.000", active: true, images: [] }] };
  const holder = { ...product, id: 7, name: "Bulb holder", brand_name: "", variants: [{ ...product.variants[0], id: 8, sku: "HOLDER", available: "5" }] };
  const charger = { ...product, id: 9, name: "Normal Full Charger", category: 13, category_name: "Wall Chargers", brand_name: "",
    variants: [{ ...product.variants[0], id: 10, available: "4" }] };
  const tree = [
    { id: 11, path: ["Electrical"] },
    { id: 14, path: ["Mobile Accessories"] },
    { id: 12, path: ["Mobile Accessories", "USB Cables"] },
    { id: 15, path: ["Mobile Accessories", "USB Cables", "Type-C"] },
    { id: 13, path: ["Mobile Accessories", "Wall Chargers"] },
  ];
  const byCategory = { 11: [product, holder], 13: [charger] };
  api.mockImplementation(async (path) =>
    path.includes("locations") ? [] : path.includes("categories/available") ? tree
      : path.includes("category-counts") ? { categories: { 11: 2, 13: 1, 15: 3 }, other: 0 }
        : path.includes("?page=") ? { results: byCategory[new URLSearchParams(path.split("?")[1]).get("category")] || [], next: null }
          : path.endsWith("/9/") ? charger : product);
  render(<MemoryRouter><ProductsPage /></MemoryRouter>);
  // Only the parent categories at first, each counting everything filed below it; no products are fetched yet.
  const mobile = await screen.findByRole("link", { name: /Mobile Accessories/ });
  expect(mobile).toHaveTextContent("4 products · 2 sub-categories");
  expect(screen.getByRole("link", { name: /Electrical/ })).toHaveTextContent("2 products");
  expect(screen.queryByRole("link", { name: /Wall Chargers/ })).not.toBeInTheDocument();
  expect(api.mock.calls.some(([path]) => path.includes("?page="))).toBe(false);

  fireEvent.click(mobile);
  expect(await screen.findByRole("heading", { level: 1, name: "Mobile Accessories" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /USB Cables/ })).toHaveTextContent("3 products · 1 sub-category");
  fireEvent.click(screen.getByRole("link", { name: /Wall Chargers/ }));
  const row = await screen.findByRole("link", { name: /Normal Full Charger/ });
  expect(api).toHaveBeenCalledWith("/api/v1/catalog/products/?page=1&category=13");
  expect(screen.getByRole("navigation", { name: "Category" })).toHaveTextContent("All products › Mobile Accessories › Wall Chargers");

  // A product page leads back to its own category.
  fireEvent.click(row);
  expect(await screen.findByRole("heading", { level: 1, name: "Normal Full Charger" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "← Back to Wall Chargers" }));
  expect(await screen.findByRole("heading", { level: 1, name: "Wall Chargers" })).toBeInTheDocument();

  // Items to restock come first within the category, and each product shows its code and stock.
  fireEvent.click(screen.getByRole("link", { name: "All products" }));
  fireEvent.click(await screen.findByRole("link", { name: /Electrical/ }));
  const bulb = await screen.findByRole("link", { name: /50W Rechargeable Bulbs/ });
  const restock = screen.getByRole("region", { name: "Needs restocking (1)" });
  expect(restock).toContainElement(bulb);
  expect(restock).not.toHaveTextContent("Bulb holder");
  expect(bulb).toHaveTextContent("DPLight");
  expect(bulb).toHaveTextContent("1 in stock · restock");
  expect(bulb).toHaveTextContent("DPLIGHT-5RB-50W-BULB");
  fireEvent.click(bulb);
  expect(await screen.findByRole("heading", { level: 1, name: "50W Rechargeable Bulbs" })).toBeInTheDocument();
  expect(screen.getByText("Rechargeable 50W bulb")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "All products" }));  // the breadcrumb leads back to the top too
  expect(await screen.findByRole("heading", { level: 1, name: "Products" })).toBeInTheDocument();
});

it("prefills and submits the receiving modal SKU using its exact compartment", async () => {
  const receivingZones = [
    {
      ...zones[0],
      stacks: [{ ...zones[0].stacks[0], categories: [{ id: 1 }] }],
    },
  ];
  api.mockImplementation(async (path) => {
    if (path.includes("locations")) return receivingZones;
    if (path.includes("categories"))
      return [{ id: 1, name: "Covers", rack_names: ["Right rack"] }];
    if (path.includes("create-inline")) return { product_id: 1, variant_id: 2 };
    return [];
  });
  render(<ReceivePage />);
  await screen.findByRole("option", {
    name: "Covers",
  });
  fireEvent.change(
    screen.getByLabelText("Merchandise category from configured racks"),
    { target: { value: "1" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Continue to items" }));
  fireEvent.click(screen.getByRole("button", { name: "+ Create new product" }));
  const form = within(
    screen.getByRole("heading", { name: "Create product" }).closest("form"),
  );
  fireEvent.change(form.getByLabelText("Product name"), {
    target: { value: "Cover" },
  });
  fireEvent.change(form.getByLabelText("Compartment", { exact: true }), {
    target: { value: "4" },
  });
  fireEvent.change(form.getByLabelText("Selling price"), {
    target: { value: "200" },
  });
  expect(form.getByLabelText("SKU")).toHaveValue("COVER");
  fireEvent.change(form.getByLabelText("Upload from storage"), {
    target: {
      files: [new File(["photo"], "type-b.png", { type: "image/png" })],
    },
  });
  expect(form.getByAltText("Product display image preview")).toHaveAttribute(
    "src",
    "blob:photo",
  );
  fireEvent.click(
    form.getByRole("button", { name: "Create and return to receipt" }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "Create product" }),
    ).not.toBeInTheDocument(),
  );
  const request = api.mock.calls.find(([path]) =>
    path.includes("create-inline"),
  );
  expect(request[1].body.get("display_image")).toBeInstanceOf(File);
  expect(Object.fromEntries(request[1].body).sku).toBe(
    "COVER",
  );
  expect(screen.getByLabelText("Compartment", { exact: true })).toHaveValue(
    "4",
  );
});

vi.mock("../../core/auth/AuthContext", () => ({
  useAuth: () => ({ user: { is_superuser: true, organization: { enabled_modules: ["inventory", "locations"] } } }),
}));

it("moves stock that is not on a shelf yet onto a compartment", async () => {
  const product = { id: 12, name: "12V 2A adaptor", active: true, product_type: "STOCK_ITEM", category_name: "Electrical Accessories",
    variants: [{ id: 12, name: "Standard", sku: "12A-ADAPTER", selling_price: "600", minimum_price: "500", available: "1", minimum_stock: "1", active: true, images: [] }],
    locations: [{ variant_id: 12, preferred_shelf: null, actual: [{ shelf_id: 42, shelf__code: "__UNPLACED__", shelf__zone__name: "Unplaced stock", quantity: "1", reserved: "0", available: "1" }] }] };
  api.mockImplementation(async (path, options) =>
    options?.method === "POST" ? { detail: "Transfer completed." }
      : path.includes("locations") ? zones
      : path.includes("?page=") ? { results: [product], next: null } : path.includes("categories") ? [] : product);
  render(<MemoryRouter initialEntries={["/admin/products?product=12"]}><ProductsPage /></MemoryRouter>);
  expect(await screen.findByText(/Not on a shelf yet/)).toBeInTheDocument();
  expect(screen.queryByText(/__UNPLACED__/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Place on a shelf" }));
  fireEvent.change(await screen.findByLabelText("Compartment"), { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Move to this compartment" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/v1/inventory/transfer/", expect.objectContaining({ method: "POST" })));
  const [, options] = api.mock.calls.find(([path]) => path === "/api/v1/inventory/transfer/");
  expect(JSON.parse(options.body)).toEqual({ variant_id: 12, source_id: 42, destination_id: 4, quantity: "1", reference: "PLACE-ON-SHELF" });
});
