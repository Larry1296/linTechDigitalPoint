import { afterEach, expect, it, vi } from "vitest";
import { api, resetCsrfToken } from "./client";
afterEach(() => { vi.unstubAllGlobals(); resetCsrfToken(); });
it("sends multipart uploads with CSRF and lets the browser set the boundary", async () => {
  resetCsrfToken();
  const fetch = vi.fn().mockResolvedValueOnce({ json: async () => ({ csrfToken: "test-token" }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) });
  vi.stubGlobal("fetch", fetch);
  const data = new FormData();
  data.set("display_image", new File(["photo"], "type-b.png", { type: "image/png" }));
  await api("/api/v1/catalog/products/create-inline/", { method: "POST", body: data });
  expect(fetch.mock.calls[1][1].body).toBe(data);
  expect(fetch.mock.calls[1][1].headers["X-CSRFToken"]).toBe("test-token");
  expect(fetch.mock.calls[1][1].headers["Content-Type"]).toBeUndefined();
});
