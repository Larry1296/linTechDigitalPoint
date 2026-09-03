import { expect, test, type Page } from "@playwright/test";

const products = [
  {
    id: 1,
    product_name: "Samsung A05 Cover",
    name: "Black",
    category: "Phone Accessories",
    selling_price: "250.00",
    available: "8.000",
    images: [],
  },
  {
    id: 2,
    product_name: "Type-C Cable",
    name: "Standard",
    category: "Chargers & Cables",
    selling_price: "300.00",
    available: "7.000",
    images: [],
  },
];

async function mockShop(page: Page) {
  let authenticated = false;
  let staff = false;
  let items: Array<Record<string, unknown>> = [];
  let stacks: Array<Record<string, unknown>> = [];
  let customZone: Record<string, unknown> | undefined;
  const zones = () => [
    {
      id: 3,
      code: "RIGHT",
      name: "Right Wall",
      width: "500.00",
      height: "250.00",
      active: true,
      stacks: stacks.filter((stack) => stack.zone === 3),
      shelves: [],
      unassigned_shelves: [],
    },
    ...(customZone
      ? [{ ...customZone, stacks: stacks.filter((stack) => stack.zone === 4) }]
      : []),
  ];
  const cart = () => ({
    id: 1,
    items,
    total: items
      .reduce((sum, item) => sum + Number(item.line_total), 0)
      .toFixed(2),
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/csrf/"))
      return route.fulfill({ json: { csrfToken: "test" } });
    if (path.endsWith("/auth/me/"))
      return route.fulfill({
        json: authenticated
          ? {
              id: 5,
              username: staff ? "owner" : "buyer",
              authenticated: true,
              is_staff: staff,
              is_superuser: staff,
              roles: staff ? [] : ["Ecommerce Customer"],
              permissions: [],
            }
          : {
              authenticated: false,
              is_staff: false,
              is_superuser: false,
              roles: [],
              permissions: [],
            },
      });
    if (path.endsWith("/auth/register/") || path.endsWith("/auth/login/")) {
      authenticated = true;
      staff =
        path.endsWith("/auth/login/") &&
        request.postDataJSON().credential === "owner";
      return route.fulfill({
        status: path.endsWith("/auth/register/") ? 201 : 200,
        json: {
          id: 5,
          username: staff ? "owner" : "buyer",
          authenticated: true,
          is_staff: staff,
          is_superuser: staff,
          roles: staff ? [] : ["Ecommerce Customer"],
          permissions: [],
        },
      });
    }
    if (path.endsWith("/store/home/"))
      return route.fulfill({
        json: {
          store: {
            name: "LinTech Digital Point",
            phone: "",
            email: "",
            address: "",
          },
          categories: [],
          featured_products: products,
          services: [],
        },
      });
    if (path.endsWith("/store/products/"))
      return route.fulfill({ json: products });
    if (path.endsWith("/inventory/dashboard/"))
      return route.fulfill({
        json: {
          today: { revenue: 0, cogs: 0, profit: 0, sales: 0 },
          inventory: {
            cost: 0,
            retail: 0,
            potential_margin: 0,
            low_stock: 0,
            total_skus: 0,
          },
          orders: {},
        },
      });
    if (path.endsWith("/locations/zones/") && request.method() === "POST") {
      const input = request.postDataJSON();
      customZone = {
        id: 4,
        code: "UPSTAIRSWINDOWDI",
        name: input.name,
        width: String(input.width),
        height: String(input.height),
        active: true,
        shelves: [],
        unassigned_shelves: [],
      };
      return route.fulfill({ status: 201, json: customZone });
    }
    if (path.endsWith("/locations/zones/"))
      return route.fulfill({ json: zones() });
    if (path.endsWith("/locations/stacks/") && request.method() === "POST") {
      const input = request.postDataJSON();
      stacks = [
        {
          id: 9,
          zone: input.zone,
          zone_name:
            input.zone === 4 ? "Upstairs Window Display" : "Right Wall",
          code: input.zone === 4 ? "UPSTAIRSWINDOWDI-R01" : "RIGHT-R01",
          display_name: input.display_name,
          x: String(input.x),
          y: String(input.y),
          width: String(input.width),
          height: String(input.height),
          depth: String(input.depth),
          rotation: String(input.rotation),
          number_of_levels: input.levels.length,
          active: true,
          notes: "",
          measurement_unit: "cm",
          levels: input.levels.map(
            (level: { compartments: number }, levelIndex: number) => ({
              id: levelIndex + 1,
              stack: 9,
              level_number: levelIndex + 1,
              y_position: "0",
              height: "52.5",
              active: true,
              shelves: Array.from(
                { length: level.compartments },
                (_, shelfIndex) => ({
                  id: levelIndex * 10 + shelfIndex + 1,
                  code: `RIGHT-R01-L${String(levelIndex + 1).padStart(2, "0")}-S${String(shelfIndex + 1).padStart(2, "0")}`,
                  display_name: `Level ${levelIndex + 1} Compartment ${shelfIndex + 1}`,
                  physical_label: "",
                  total_quantity: "0",
                  active: true,
                }),
              ),
            }),
          ),
        },
      ];
      return route.fulfill({ status: 201, json: stacks[0] });
    }
    if (path.endsWith("/commerce/cart/") && request.method() === "POST") {
      const variant = Number(request.postDataJSON().variant_id);
      const product = products.find((item) => item.id === variant)!;
      items.push({
        id: variant,
        variant,
        product_name: product.product_name,
        variant_name: product.name,
        quantity: "1.000",
        unit_price: product.selling_price,
        line_total: product.selling_price,
        available: product.available,
      });
      return route.fulfill({ json: cart() });
    }
    if (path.endsWith("/commerce/cart/"))
      return route.fulfill({ json: cart() });
    if (path.endsWith("/commerce/checkout/")) {
      items = [];
      return route.fulfill({
        status: 201,
        json: { id: 42, number: "LT-WEB-00042", items: [], total: "550.00" },
      });
    }
    if (path.endsWith("/commerce/orders/42/"))
      return route.fulfill({
        json: {
          id: 42,
          number: "LT-WEB-00042",
          items: [],
          total: "550.00",
          status: "AWAITING_PAYMENT",
        },
      });
    return route.fulfill({ json: [] });
  });
}

test("new customer keeps the full cart through registration and checkout", async ({
  page,
}) => {
  await mockShop(page);
  await page.goto("/shop");
  await page.getByRole("button", { name: "Add to cart" }).nth(0).click();
  await page.getByRole("button", { name: "Add to cart" }).nth(1).click();
  await page.getByRole("link", { name: /Cart/ }).first().click();
  await expect(page.getByText("Samsung A05 Cover")).toBeVisible();
  await expect(page.getByText("Type-C Cable")).toBeVisible();
  await page.getByRole("link", { name: "Proceed to checkout" }).click();
  await expect(page).toHaveURL(/\/login\?next=%2Fcheckout/);
  await page.getByRole("link", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/register\?next=%2Fcheckout/);
  await page.getByLabel("Full name").fill("New Buyer");
  await page.getByLabel("Username", { exact: true }).fill("newbuyer");
  await page.getByLabel("Email").fill("new@example.test");
  await page.getByLabel("Password", { exact: true }).fill("Strong-pass-1296");
  await page.getByLabel("Confirm password").fill("Strong-pass-1296");
  await page.getByRole("button", { name: "Register" }).click();
  await expect(page).toHaveURL(/\/checkout$/);
  await expect(page.getByText(/Samsung A05 Cover/)).toBeVisible();
  await expect(page.getByText(/Type-C Cable/)).toBeVisible();
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page).toHaveURL(/\/account\/orders\/42$/);
  await page.getByRole("link", { name: /Cart/ }).first().click();
  await expect(page.getByText("Your cart is empty.")).toBeVisible();
});

test("staff use the shared login and return to their intended page", async ({
  page,
}) => {
  await mockShop(page);
  await page.goto("/admin-app/digital-shop");
  await expect(page).toHaveURL(/\/login\?next=%2Fadmin-app%2Fdigital-shop/);
  await page.getByLabel("Username or email").fill("owner");
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/admin-app\/digital-shop$/);
});

test("Django superuser is displayed as Owner and defaults to the admin dashboard", async ({
  page,
}) => {
  await mockShop(page);
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("owner");
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/admin-app\/dashboard$/);
  await expect(page.getByText("Owner", { exact: true })).toBeVisible();
});

test("Owner previews and creates a complete unequal shelf stack", async ({
  page,
}) => {
  await mockShop(page);
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("owner");
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.goto("/admin-app/digital-shop");
  await page.getByRole("button", { name: "Create First Shelf Stack" }).click();
  await page.getByLabel("Shop area").selectOption("new");
  await page.getByLabel("Area name").fill("Upstairs Window Display");
  await page.getByLabel("Area width (cm)").fill("725");
  await page.getByLabel("Area height (cm)").fill("315");
  await page.getByLabel("Stack name").fill("Phone Accessories Rack");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("L4-S3", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Create Shelf Stack" }).click();
  await expect(
    page.getByText("UPSTAIRSWINDOWDI-R01", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Phone Accessories Rack", { exact: true }).first(),
  ).toBeVisible();
});
