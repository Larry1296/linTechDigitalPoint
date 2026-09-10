import { expect, test } from "@playwright/test";

const sections = ["Headphones", "Charging Cables", "Memory Cards", "Wall Chargers", "Accessories"].map((name, index) => ({
  id: index + 1, name, slug: name.toLowerCase().replaceAll(" ", "-"),
  products: Array.from({ length: index + 1 }, (_, variant) => ({
    id: index * 10 + variant + 1,
    display_name: name === "Memory Cards" ? "Boost Memory Card — " + (variant ? "8GB" : "16GB") : name + " — White — " + (variant + 1),
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
    const json = path.endsWith("/store/home/")
      ? { store: { name: "LinTech" }, categories: [], category_sections: sections, cyber_services: [] }
      : path.endsWith("/store/products/") ? products
      : path.endsWith("/auth/me/") ? { authenticated: false }
      : { items: [], total: "0.00" };
    return route.fulfill({ json });
  });
});

for (const width of [1440, 1024, 768, 375]) {
  test("evenly distributed cards without clipping at " + width + "px", async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    await expect(page.locator(".categoryProductSection")).toHaveCount(5);
    for (const section of sections) {
      const region = page.getByRole("region", { name: section.name, exact: true });
      await expect(region.locator(".productCard")).toHaveCount(section.products.length);
      await checkGrid(region.locator(".categoryProductGrid"), width);
    }
    await page.screenshot({ path: testInfo.outputPath("homepage.png"), fullPage: true });
    for (const path of ["/shop", "/shop?category=2"]) {
      await page.goto(path);
      await expect(page.locator(".productCard")).toHaveCount(15);
      await checkGrid(page.locator(".productGrid"), width);
    }
    await page.screenshot({ path: testInfo.outputPath("shop.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

async function checkGrid(grid, width) {
  const bounds = await grid.boundingBox();
  const boxes = [];
  for (const card of await grid.locator(".productCard").all()) {
    const box = await card.boundingBox();
    boxes.push(box);
    expect(box.width).toBeLessThanOrEqual(width <= 520 ? 340 : 280);
    expect(box.width).toBeGreaterThanOrEqual(230);
    expect(box.x).toBeGreaterThanOrEqual(bounds.x);
    expect(box.x + box.width).toBeLessThanOrEqual(bounds.x + bounds.width + 1);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await checkImageAndActions(card);
  }
  const firstRow = boxes.filter((box) => Math.abs(box.y - boxes[0].y) < 1);
  const left = firstRow[0].x - bounds.x;
  const last = firstRow.at(-1);
  const right = bounds.x + bounds.width - last.x - last.width;
  expect(left).toBeCloseTo(right, 0);
  for (let i = 1; i < firstRow.length; i++) {
    expect(firstRow[i].x - firstRow[i - 1].x - firstRow[i - 1].width).toBeGreaterThanOrEqual(16);
  }
  if (firstRow.length > 2) {
    const distance = firstRow[1].x - firstRow[0].x;
    for (let i = 2; i < firstRow.length; i++)
      expect(firstRow[i].x - firstRow[i - 1].x).toBeCloseTo(distance, 0);
  }
  if (width === 1440) expect(firstRow).toHaveLength(Math.min(4, boxes.length));
  if (width === 375) {
    expect(firstRow).toHaveLength(1);
    for (const box of boxes)
      expect(box.x + box.width / 2).toBeCloseTo(bounds.x + bounds.width / 2, 0);
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
