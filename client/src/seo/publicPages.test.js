import { expect, test } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { cwd } from "node:process";
import { PUBLIC_PAGES, applyPage, pageHref, pageUrl, sectionOf } from "./publicPages";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const html = read("../../index.html");

test("index.html carries the home page's tags exactly as the build writes them", () => {
  expect(applyPage(html, PUBLIC_PAGES[0])).toBe(html);
});

test("each public page gets its own title, description, links and text", () => {
  const pricing = applyPage(html, PUBLIC_PAGES.find((page) => page.path === "/pricing"));
  expect(pricing).toContain("<title>Pricing – DukaFlow | First Month Free, Then From KES 500</title>");
  expect(pricing).toContain('<link rel="canonical" href="https://dukaflow.co.ke/pricing/" />');
  expect(pricing).toContain('<meta property="og:url" content="https://dukaflow.co.ke/pricing/" />');
  expect(pricing).toContain("<h1>DukaFlow pricing</h1>");
  expect(pricing).not.toContain("<h1>DukaFlow: POS");
  expect(pricing).toContain('content="https://dukaflow.co.ke/og-image.png"');
});

test("a missing tag stops the build instead of publishing a page with the wrong tags", () => {
  expect(() => applyPage(html.replace(/<link rel="canonical"[^>]*>/, ""), PUBLIC_PAGES[1])).toThrow(/missing/);
});

test("the sitemap lists exactly the public pages, and robots.txt keeps crawlers out of the workspace", () => {
  const listed = [...read("../../public/sitemap.xml").matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
  expect(listed).toEqual(PUBLIC_PAGES.map((page) => pageUrl(page.path)));
  const robots = read("../../public/robots.txt");
  for (const path of ["/admin", "/r/", "/reset-password"]) expect(robots).toContain(`Disallow: ${path}`);
  expect(robots).toContain("Sitemap: https://dukaflow.co.ke/sitemap.xml");
});

test("the public section pages are linked with a trailing slash and open at their section", () => {
  expect(pageHref("/")).toBe("/");
  expect(pageHref("/pricing")).toBe("/pricing/");
  expect(sectionOf("/pricing/")).toBe("pricing");
  expect(sectionOf("/pricing")).toBe("pricing");
  expect(sectionOf("/")).toBeNull();
  expect(sectionOf("/admin/pos")).toBeNull();
});

test("no link in the app points at a section page without its slash (the host would answer with the home page)", () => {
  const files = [];
  const walk = (dir) => readdirSync(dir).forEach((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.jsx?$/.test(name) && !/\.test\.jsx?$/.test(name)) files.push(path);
  });
  walk(join(cwd(), "src"));
  expect(files.length).toBeGreaterThan(50);
  const sections = PUBLIC_PAGES.filter((page) => page.path !== "/").map((page) => page.path.slice(1)).join("|");
  const wrong = new RegExp(`(?:to|href)=["'{\`]+/(?:#)?(?:${sections})(?:["'\`#?])`);
  const offenders = files.filter((file) => wrong.test(readFileSync(file, "utf8")));
  expect(offenders).toEqual([]);
});
