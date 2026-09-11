import { expect, test } from "@playwright/test";

const sections = ["Headphones", "Charging Cables", "Memory Cards", "Wall Chargers", "Accessories"].map((name, index) => ({
  id: index + 1, name, slug: name.toLowerCase().replaceAll(" ", "-"),
  products: Array.from({ length: index + 1 }, (_, variant) => ({
    id: index * 10 + variant + 1,
    display_name: name === "Memory Cards" ? "Boost Memory Card — " + (variant ? "8GB" : "16GB") : name + " — White — " + (variant + 1) + (variant === 1 ? " ExtraLongProductName".repeat(5) : ""),
    online_orderable: true, category: name, selling_price: "250.00", available: 3,
    images: [{ url: name === "Memory Cards" ? "/layout-memory-" + (variant ? "8" : "16") + ".webp" : "/layout-product.svg" }],
  })),
}));
const products = sections.flatMap((section) => section.products);

test.beforeEach(async ({ page }) => {
  await page.route("**/layout-product.svg", (route) => route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="160"><rect x="25" y="10" width="50" height="140" rx="12" fill="#287a67"/></svg>',
  }));
  await page.route("**/layout-memory-*.webp", (route) => {
    const capacity = route.request().url().includes("-16.") ? "16" : "8";
    // Optional real local uploads for visual review; CI uses square catalogue fixtures.
    if (process.env.PRODUCT_LAYOUT_IMAGE_DIR) {
      const file = capacity === "16" ? "508c8ab6b1d14f54a9fd8e66f62616af.webp" : "5963ac2af9d0435da0a9bcdbadc767ea.webp";
      return route.fulfill({ path: process.env.PRODUCT_LAYOUT_IMAGE_DIR + "/" + file });
    }
    return route.fulfill({ contentType: "image/svg+xml", body:
      '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="white"/><rect x="65" y="15" width="170" height="270" rx="12" fill="#eee" stroke="#aaa"/><text x="100" y="110" font-size="28">' + capacity + 'GB</text></svg>' });
  });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const variant = products.find((product) => path === "/api/v1/store/products/" + product.id + "/");
    const json = variant ? { ...variant, variants: [variant] } : path.endsWith("/store/home/")
      ? { store: { name: "LinTech" }, categories: [], category_sections: sections, cyber_services: [] }
      : path.endsWith("/store/products/") ? (sections.find((section) => String(section.id) === new URL(route.request().url()).searchParams.get("product__category"))?.products || products)
      : path.endsWith("/auth/me/") ? { authenticated: false }
      : { items: [], total: "0.00" };
    return route.fulfill({ json });
  });
});

for (const width of [1440, 1024, 1023, 700, 699, 440, 439, 375, 320]) {
  test("fixed left-aligned tracks without clipping at " + width + "px", async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    await expect(page.locator(".categoryProductSection")).toHaveCount(5);
    let previousGrid;
    let homeCardWidth;
    for (const section of sections) {
      const region = page.getByRole("region", { name: section.name, exact: true });
      await expect(region.locator(".productCard")).toHaveCount(section.products.length);
      const heading = await region.locator(".categorySectionHeading").boundingBox();
      const grid = await region.locator(".categoryProductGrid").boundingBox();
      expect(grid.y - heading.y - heading.height).toBeCloseTo(14, 0);
      if (previousGrid) {
        const separation = heading.y - previousGrid.y - previousGrid.height;
        expect(separation).toBeGreaterThanOrEqual(24);
        expect(separation).toBeLessThanOrEqual(36);
      }
      previousGrid = grid;
      await expect(region).toHaveCSS("margin-top", "0px");
      await expect(region).toHaveCSS("margin-bottom", "0px");
      await checkGrid(region.locator(".categoryProductGrid"), width);
      homeCardWidth = (await region.locator(".productCard").first().boundingBox()).width;
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath("homepage.png"), fullPage: true });
    for (const path of ["/shop", "/shop?category=1", "/shop?category=2", "/shop?category=3"]) {
      await page.goto(path);
      await expect(page.locator(".productCard")).toHaveCount(path === "/shop" ? 15 : Number(path.at(-1)));
      await checkGrid(page.locator(".productGrid"), width);
      expect((await page.locator(".productCard").first().boundingBox()).width).toBeCloseTo(homeCardWidth, 0);
    }
    await page.screenshot({ path: testInfo.outputPath("shop.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

async function checkGrid(grid, width) {
  const bounds = await grid.boundingBox();
  const boxes = [];
  const columns = width >= 1024 ? 4 : width >= 700 ? 3 : width >= 440 ? 2 : 1;
  await expect(grid).toHaveCSS("gap", "24px");
  expect(await grid.evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(" ").length)).toBe(columns);
  for (const card of await grid.locator(".productCard").all()) {
    const box = await card.boundingBox();
    boxes.push(box);
    expect(box.width).toBeCloseTo((bounds.width - 24 * (columns - 1)) / columns, 0);
    expect(box.x).toBeGreaterThanOrEqual(bounds.x);
    expect(box.x + box.width).toBeLessThanOrEqual(bounds.x + bounds.width + 1);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await checkImageAndActions(card);
  }
  const firstRow = boxes.filter((box) => Math.abs(box.y - boxes[0].y) < 1);
  expect(firstRow).toHaveLength(Math.min(columns, boxes.length));
  for (let i = 0; i < boxes.length; i++) {
    expect(boxes[i].x).toBeCloseTo(bounds.x + (i % columns) * (boxes[i].width + 24), 0);
    const rowStart = boxes[Math.floor(i / columns) * columns];
    expect(boxes[i].y).toBeCloseTo(rowStart.y, 0);
    expect(boxes[i].height).toBeCloseTo(rowStart.height, 0);
  }
  // Rows may wrap, but no two card rectangles may intersect.
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++)
      expect(boxes[i].x + boxes[i].width <= boxes[j].x + 1 ||
        boxes[j].x + boxes[j].width <= boxes[i].x + 1 ||
        boxes[i].y + boxes[i].height <= boxes[j].y + 1 ||
        boxes[j].y + boxes[j].height <= boxes[i].y + 1).toBe(true);
}

async function checkImageAndActions(card) {
  const image = card.locator(".productImage");
  const bounds = await image.boundingBox();
  expect(bounds.height).toBeCloseTo(bounds.width, 0);
  await expect(image).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(image).toHaveCSS("padding", "8px");
  await expect(image.locator("img")).toHaveCSS("object-fit", "contain");
  await expect(image.locator("img")).toHaveCSS("object-position", "50% 50%");
  const action = await card.locator(".cardActions, :scope > a.button").boundingBox();
  const box = await card.boundingBox();
  expect(box.y + box.height - action.y - action.height).toBeCloseTo(17, 0);
}

for (const theme of ["light", "dark"]) {
  for (const width of [1440, 375]) {
    test("neutral photography canvas in " + theme + " at " + width, async ({ page }, testInfo) => {
      await page.addInitScript((theme) => localStorage.setItem("theme", theme), theme);
      await page.setViewportSize({ width, height: 1000 });
      // Portrait packaging and square catalogue imagery.
      for (const product of [products[0], products.find((p) => p.category === "Memory Cards")]) {
        await page.goto("/products/" + product.id);
        const canvas = page.locator(".productImage.large");
        await expect(canvas).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        const box = await canvas.boundingBox();
        expect(box.width).toBeCloseTo(box.height, 0);
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        await expect(canvas).toHaveCSS("background-color", "rgb(255, 255, 255)");
        await expect(canvas).toHaveCSS("padding", "8px");
        await expect(canvas).toHaveCSS("border-radius", "14px");
        const img = canvas.locator("img");
        await expect(img).toHaveCSS("object-fit", "contain");
        await expect(img).toHaveCSS("object-position", "50% 50%");
        await expect(img).toHaveCSS("filter", "none");
        await expect(img).toHaveCSS("opacity", "1");
        expect(await img.evaluate((node) => node.complete && node.naturalWidth > 0)).toBe(true);
        if (theme === "dark") await expect(canvas).not.toHaveCSS("box-shadow", "none");
        await page.screenshot({ path: testInfo.outputPath("detail-" + product.id + ".png"), fullPage: true });
      }
      await page.goto("/shop");
      await expect(page.locator(".productCard")).toHaveCount(products.length);
      await checkGrid(page.locator(".productGrid"), width);
    });
  }
}

test("theme changes preserve homepage and shop card dimensions", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const path of ["/", "/shop"]) {
    await page.goto(path);
    await expect(page.locator(".productCard")).toHaveCount(products.length);
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    const measure = () => page.locator(".productCard").evaluateAll((cards) => cards.map((card) => {
      const { x, y, width, height } = card.getBoundingClientRect();
      return { x, y, width, height };
    }));
    const light = await measure();
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    expect(await measure()).toEqual(light);
  }
});
