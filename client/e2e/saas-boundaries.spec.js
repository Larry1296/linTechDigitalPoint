import { test, expect } from '@playwright/test';
import { dashboardSnapshot } from './fixtures.js';

async function mockSession(page, authenticated = false) {
  const organization = {id: 1, name: 'Test business', currency: 'USD', timezone: 'America/New_York', enabled_modules: ['inventory', 'pos', 'reports'], subscription_status: 'ACTIVE'};
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/tenancy/platform/')) return route.fulfill({json: {name: 'Business Management Platform', contact_email: ''}});
    if (path.endsWith('/auth/me/')) return route.fulfill({json: authenticated ? {authenticated: true, username: 'test-owner', organization, memberships: [{organization, role: 'OWNER'}, {organization: {id: 2, name: 'Second business'}, role: 'OWNER'}], roles: ['OWNER'], permissions: ['catalog.view_product', 'commerce.add_sale', 'commerce.view_sale']} : {authenticated: false}});
    if (path.endsWith('/inventory/dashboard/')) return route.fulfill({json: dashboardSnapshot(organization)});
    return route.fulfill({json: []});
  });
}

for (const width of [390, 768, 1440]) {
  test(`public platform and private boundary at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    await mockSession(page);
    await page.goto('/');
    await expect(page.getByRole('heading', {name: /Keep your business/})).toBeVisible();
    await expect(page.getByText(/linTech/i)).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width <= 1100) await page.getByRole('button', {name: 'Open navigation', exact: true}).click();
    await page.getByRole('navigation').getByRole('link', {name: 'Features', exact: true}).click();
    await expect(page).toHaveURL(/#features$/);
    await page.goto('/admin/dashboard');
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Fdashboard/);
  });

  test(`tenant identity and session refresh at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    await mockSession(page, true);
    await page.goto('/admin');
    await expect(page).toHaveURL(/\/admin\/dashboard$/);
    await expect(page.getByRole('heading', {name: 'Test business', exact: true})).toBeVisible();
    await expect(page.getByLabel('Active organization')).toHaveValue('1');
    await page.reload();
    await expect(page.getByRole('heading', {name: 'Test business', exact: true})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.goto('/');
    await expect(page.getByRole('heading', {name: /Keep your business/})).toBeVisible();
    await expect(page.getByRole('heading', {name: 'Test business', exact: true})).toHaveCount(0);
  });
}


test("theme follows the system, resets overrides on reload, and applies across public and private pages", async ({page}) => {
  await page.emulateMedia({colorScheme: "dark"});
  await mockSession(page, true);
  await page.goto("/");
  const root = page.locator("html");
  await expect(page.getByRole("combobox", {name: "Theme", exact:true})).toHaveValue("system");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({colorScheme: "light"});
  await expect(root).toHaveAttribute("data-theme", "light");
  await page.goto("/admin/dashboard");
  const topbar = page.getByRole("banner", {name:"Business topbar"});
  await expect(topbar).toBeVisible();
  await topbar.getByRole("combobox", {name:"Theme", exact:true}).selectOption("dark");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(topbar.getByRole("combobox", {name:"Theme", exact:true})).toHaveValue("system");
  await expect(root).toHaveAttribute("data-theme", "light");
  await page.goto("/");
  await expect(root).toHaveAttribute("data-theme", "light");
  await page.getByRole("combobox", {name:"Theme", exact:true}).selectOption("dark");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".saasSite")).toHaveCSS("background-color", "rgb(6, 16, 31)");
  await page.getByRole("combobox", {name:"Theme", exact:true}).selectOption("light");
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(page.locator(".saasSite")).toHaveCSS("background-color", "rgb(244, 247, 252)");
  // The sign-in page has no theme picker: a fresh page follows the system again.
  await page.goto("/login");
  await page.emulateMedia({colorScheme: "dark"});
  await expect(root).toHaveAttribute("data-theme", "dark");
});
