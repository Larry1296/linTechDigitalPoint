import { env } from "node:process";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { PUBLIC_PAGES, applyPage } from "./src/seo/publicPages.js";

// Each public page gets its own HTML file (dist/pricing/index.html and dist/pricing.html, ...) carrying its own title, description,
// link-preview tags and plain text, so crawlers and link previews read them without running JavaScript.
// The app inside is the same one: React replaces the text on start, and every other path still gets index.html.
function seoPages() {
  return {
    name: "seo-pages",
    apply: "build",
    writeBundle(options) {
      const dir = options.dir;
      const html = readFileSync(join(dir, "index.html"), "utf8");
      for (const page of PUBLIC_PAGES) {
        const written = applyPage(html, page);
        if (page.path === "/") { writeFileSync(join(dir, "index.html"), written); continue; }
        // Hosts differ in which file answers /pricing: pricing/index.html or pricing.html. Both are written.
        const slug = page.path.slice(1);
        mkdirSync(join(dir, slug), { recursive: true });
        writeFileSync(join(dir, slug, "index.html"), written);
        writeFileSync(join(dir, `${slug}.html`), written);
      }
    },
  };
}
export default defineConfig({
  plugins: [react(), tailwindcss(), seoPages()],
  server: { proxy: { "/api": (env.VITE_API_PROXY || "http://127.0.0.1:8000"), "/media": (env.VITE_API_PROXY || "http://127.0.0.1:8000"), "/platform-admin": (env.VITE_API_PROXY || "http://127.0.0.1:8000") } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.js",
    exclude: ["e2e/**", "node_modules/**"],
  },
});
