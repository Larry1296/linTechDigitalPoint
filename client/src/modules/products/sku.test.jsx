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
import { suggestProductSku, findSkuCompartment } from "./sku";
import { ProductSkuField } from "./components/ProductSkuField";
import { ProductForm } from "./ProductForm";
import { api } from "../../core/api/client";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
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
  api.mockImplementation(async (path) =>
    path.includes("categories") ? [{ id: 1, name: "Covers" }] : [],
  );
});
describe("searchable SKU suggestions", () => {
  it("includes product, variant, and the exact permanent rack/level/compartment code", () => {
    expect(
      suggestProductSku({
        productName: "Smartphone Cover",
        variantName: "Samsung A15 / Black",
        compartmentCode: "RIGHT-R01-L01-S02",
      }),
    ).toBe("SMARTPHONE-COVER-SAMSUNG-A15-BLACK-RIGHT-R01-L01-S02");
  });
  it("normalizes punctuation and omits the Standard variant", () => {
    expect(
      suggestProductSku({
        productName: "  Café & cable! ",
        compartmentCode: "RIGHT-R01-L01-S02",
      }),
    ).toBe("CAFE-CABLE-RIGHT-R01-L01-S02");
    expect(suggestProductSku({ productName: "" })).toBe("");
  });
  it("keeps the exact location within the database's 64-character limit", () => {
    const code = "BACKWALL-R01-L02-S01";
    const result = suggestProductSku({
      productName: "Very long name ".repeat(20),
      variantName: "Blue",
      compartmentCode: code,
    });
    expect(result.length).toBeLessThanOrEqual(64);
    expect(result.endsWith(code)).toBe(true);
  });
  it("does not include a shelf in a service code", () => {
    expect(
      suggestProductSku({
        productName: "Printing",
        productType: "SERVICE",
        compartmentCode: "RIGHT-R01-L01-S02",
      }),
    ).toBe("PRINTING-SERVICE");
  });
  it("resolves actual compartment records and ignores inactive locations", () => {
    expect(findSkuCompartment(zones, "4").code).toBe("RIGHT-R01-L01-S02");
    expect(findSkuCompartment(zones, 99)).toBeNull();
    expect(findSkuCompartment([{ ...zones[0], active: false }], 4)).toBeNull();
  });
  it("updates suggestions while preserving manual overrides until reset", () => {
    const { rerender } = render(
      <ProductSkuField productName="Cover" zones={zones} />,
    );
    expect(screen.getByLabelText("SKU")).toHaveValue("COVER");
    rerender(
      <ProductSkuField
        productName="Cover"
        variantName="Blue"
        zones={zones}
        shelfId={4}
      />,
    );
    expect(screen.getByLabelText("SKU")).toHaveValue(
      "COVER-BLUE-RIGHT-R01-L01-S02",
    );
    fireEvent.change(screen.getByLabelText("SKU"), {
      target: { value: "CUSTOM-001" },
    });
    rerender(
      <ProductSkuField productName="Padlock" zones={zones} shelfId={4} />,
    );
    expect(screen.getByLabelText("SKU")).toHaveValue("CUSTOM-001");
    fireEvent.click(screen.getByRole("button", { name: "Use suggested SKU" }));
    expect(screen.getByLabelText("SKU")).toHaveValue(
      "PADLOCK-RIGHT-R01-L01-S02",
    );
  });
  it("submits the suggested SKU with the selected exact compartment", async () => {
    const saved = vi.fn();
    render(<ProductForm zones={zones} preferredShelf={4} onSaved={saved} />);
    await screen.findByRole("option", { name: /Covers/ });
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
      "SMARTPHONE-COVER-BLACK-RIGHT-R01-L01-S02",
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Product" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    const request = api.mock.calls.find(([path]) =>
      path.includes("create-with-stock"),
    );
    expect(JSON.parse(request[1].body)).toEqual(
      expect.objectContaining({
        sku: "SMARTPHONE-COVER-BLACK-RIGHT-R01-L01-S02",
        preferred_shelf_id: 4,
      }),
    );
  });
});

it("searches the product list using a product name and rack/compartment code", async () => {
  api.mockImplementation(async (path) =>
    path.includes("locations")
      ? zones
      : [
          {
            id: 1,
            name: "Cover",
            product_type: "STOCK_ITEM",
            variants: [
              { id: 2, name: "Black", sku: "COVER-BLACK-RIGHT-R01-L01-S02" },
            ],
            locations: [],
          },
        ],
  );
  render(<ProductsPage />);
  await screen.findByRole("heading", { name: "Cover" });
  const search = screen.getByLabelText("Search products, variants or SKU");
  fireEvent.change(search, { target: { value: "cover right-r01 l01-s02" } });
  expect(screen.getByRole("heading", { name: "Cover" })).toBeInTheDocument();
  fireEvent.change(search, { target: { value: "BACKWALL-R01" } });
  expect(
    screen.getByText("No products match your search."),
  ).toBeInTheDocument();
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
    name: "Covers — available in Right rack",
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
  expect(form.getByLabelText("SKU")).toHaveValue("COVER-RIGHT-R01-L01-S02");
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
  expect(JSON.parse(request[1].body).sku).toBe("COVER-RIGHT-R01-L01-S02");
  expect(screen.getByLabelText("Compartment", { exact: true })).toHaveValue(
    "4",
  );
});
