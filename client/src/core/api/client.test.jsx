import { afterEach, expect, it, vi } from "vitest";
import { api, resetCsrfToken, SESSION_EXPIRED_MESSAGE } from "./client";
const response = (status, data) => ({
  status,
  ok: status < 400,
  json: async () => data,
});
it.each([401, 403])(
  "notifies once for concurrent expired requests returning %s",
  async (status) => {
    const listener = vi.fn();
    window.addEventListener("session-expired", listener);
    const fetch = vi.fn(async (path) =>
      path.endsWith("/me/")
        ? response(200, { authenticated: false })
        : path.endsWith("/login/")
          ? response(200, { authenticated: true })
          : response(status, {
              detail: "Authentication credentials were not provided.",
            }),
    );
    vi.stubGlobal("fetch", fetch);
    await api("/api/v1/auth/login/");
    const results = await Promise.allSettled([
      api("/api/v1/inventory/receipts/"),
      api("/api/v1/locations/zones/"),
    ]);
    for (const result of results)
      expect(result.reason.message).toBe(SESSION_EXPIRED_MESSAGE);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(
      fetch.mock.calls.filter(([path]) => path.endsWith("/me/")),
    ).toHaveLength(1);
    window.removeEventListener("session-expired", listener);
  },
);
it.each([true, "offline"])(
  "keeps permission errors when session verification is %s",
  async (authenticated) => {
    const listener = vi.fn();
    window.addEventListener("session-expired", listener);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path) => {
        if (path.endsWith("/me/")) {
          if (authenticated === "offline") throw new Error("Network error");
          return response(200, { authenticated });
        }
        return response(403, {
          detail: "You do not have permission to perform this action.",
        });
      }),
    );
    await expect(api("/api/v1/inventory/receipts/")).rejects.toThrow(
      "You do not have permission",
    );
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener("session-expired", listener);
  },
);
it("does not interpret invalid login credentials as session expiry", async () => {
  const fetch = vi.fn(async () =>
    response(401, { detail: "Invalid credentials" }),
  );
  vi.stubGlobal("fetch", fetch);
  await expect(api("/api/v1/auth/login/")).rejects.toThrow(
    "Invalid credentials",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});
afterEach(() => {
  vi.unstubAllGlobals();
  resetCsrfToken();
});
it("sends multipart uploads with CSRF and lets the browser set the boundary", async () => {
  resetCsrfToken();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce({ json: async () => ({ csrfToken: "test-token" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) });
  vi.stubGlobal("fetch", fetch);
  const data = new FormData();
  data.set(
    "display_image",
    new File(["photo"], "type-b.png", { type: "image/png" }),
  );
  await api("/api/v1/catalog/products/create-inline/", {
    method: "POST",
    body: data,
  });
  expect(fetch.mock.calls[1][1].body).toBe(data);
  expect(fetch.mock.calls[1][1].headers["X-CSRFToken"]).toBe("test-token");
  expect(fetch.mock.calls[1][1].headers["Content-Type"]).toBeUndefined();
});
