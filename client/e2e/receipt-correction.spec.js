import { expect, test } from "@playwright/test";

const reason =
  "Amaya 10W wall-charger buying price was mistakenly entered against the cable.";
for (const [width, theme] of [
  [1440, "light"],
  [390, "dark"],
]) {
  test(`receipt correction review and confirmation at ${width}px in ${theme}`, async ({
    page,
  }, testInfo) => {
    let posted;
    const line = {
      id: 22,
      variant_id: 7,
      product_name: "Amaya charging cable",
      variant_name: "White — 1.2m",
      sku: "AMAYA-CABLE",
      quantity: "3.000",
      unit_cost: "160.00",
      line_cost: "480.00",
      updated_at: "2026-09-11T09:00:00Z",
      placements: [{ shelf_id: 1, code: "A1", quantity: "3.000" }],
      corrections: [],
    };
    const receipt = {
      id: 145,
      receipt_number: "REC-145",
      received_at: line.updated_at,
      supplier_name: "Supplier",
      lines: [line],
    };
    await page.emulateMedia({ colorScheme: theme });
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      let json = {};
      if (path.endsWith("/auth/me/"))
        json = {
          authenticated: true,
          is_staff: true,
          is_superuser: true,
          username: "admin",
          permissions: [],
          roles: [],
        };
      else if (path.endsWith("/auth/csrf/")) json = { csrfToken: "test" };
      else if (path.endsWith("/cart/")) json = { items: [], total: "0" };
      else if (path.endsWith("/receipts/"))
        json = [{ ...receipt, total_units: "3.000", line_count: 1 }];
      else if (path.endsWith("/receipts/145/")) json = receipt;
      else if (path.includes("/variants/search/")) json = [{ ...line, id: 7 }];
      else if (path.endsWith("/correct/")) {
        posted = request.postDataJSON();
        json = {
          ...receipt,
          lines: [
            {
              ...line,
              unit_cost: "80.00",
              line_cost: "240.00",
              corrections: [
                {
                  id: 1,
                  administrator: "admin",
                  created_at: line.updated_at,
                  reason,
                  before: { ...line, line_total: "480.00" },
                  after: { ...line, unit_cost: "80.00", line_total: "240.00" },
                },
              ],
            },
          ],
        };
      }
      await route.fulfill({ json });
    });
    await page.goto("/admin-app/receipts");
    if (width < 700)
      await page.getByRole("button", { name: "Open dashboard menu" }).click();
    await expect(
      page.getByRole("link", { name: "Receipt History", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("link", { name: "Receipt History", exact: true })
      .click();
    await page.getByRole("link", { name: "Receipt 145 · REC-145" }).click();
    await page
      .getByRole("button", { name: "Correct receipt line", exact: true })
      .click();
    await page
      .getByLabel("Buying price per unit (KSh)", { exact: true })
      .fill("80");
    await page.getByLabel("Correction reason", { exact: true }).fill(reason);
    await expect(
      page.getByRole("cell", { name: "KSh 240.00", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: testInfo.outputPath("review.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Review correction" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Quantity: 3 → 3");
    await expect(dialog).toContainText("KSh 480.00 → KSh 240.00");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(posted).toBeUndefined();
    await page.getByRole("button", { name: "Review correction" }).click();
    await page
      .getByRole("button", { name: "Confirm correction", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "Receipt line corrected",
    );
    expect(posted).toMatchObject({
      variant_id: 7,
      unit_cost: "80",
      received_quantity: "3.000",
      confirmed: true,
      reason,
    });
    expect(posted).not.toHaveProperty("placements");
    await expect(
      page.getByRole("heading", { name: "Correction history" }),
    ).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("audit.png"),
      fullPage: true,
    });
  });
}
