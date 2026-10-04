import { env } from "node:process";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": (env.VITE_API_PROXY || "http://127.0.0.1:8000"), "/media": (env.VITE_API_PROXY || "http://127.0.0.1:8000"), "/platform-admin": (env.VITE_API_PROXY || "http://127.0.0.1:8000") } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.js",
    exclude: ["e2e/**", "node_modules/**"],
  },
});
