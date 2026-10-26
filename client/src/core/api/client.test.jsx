import { afterEach, expect, it, vi } from "vitest";
import { api, clearAccessToken, resetCsrfToken, setActiveOrganization, setWorkspaceLocked, SERVER_UNREACHABLE, SESSION_EXPIRED_MESSAGE } from "./client";
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
    try {
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
    } finally {
      window.removeEventListener("session-expired", listener);
    }
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
it("does not silently renew access after a business request fails", async () => {
  const fetch = vi.fn(async path => path.endsWith("/me/")
    ? response(200, { authenticated: true }) : response(403, { detail: "Permission denied" }));
  vi.stubGlobal("fetch", fetch);
  await expect(api("/api/v1/inventory/dashboard/")).rejects.toThrow("Permission denied");
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(["/api/v1/inventory/dashboard/", "/api/v1/auth/me/"]);
});
it("pauses locked reads until unlock without automatically renewing the token", async () => {
  const listener = vi.fn();
  window.addEventListener("session-locked", listener);
  const fetch = vi.fn().mockResolvedValueOnce(response(423, { code: "session_locked", session: { locked: true } }))
    .mockResolvedValueOnce(response(200, { value: "fresh" }));
  vi.stubGlobal("fetch", fetch);
  const request = api("/api/v1/inventory/dashboard/");
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(listener).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledTimes(1);
  setWorkspaceLocked(false);
  await expect(request).resolves.toEqual({ value: "fresh" });
  window.removeEventListener("session-locked", listener);
});
it("never queues or replays a locked mutation", async () => {
  setWorkspaceLocked(true);
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await expect(api("/api/v1/inventory/receive/", { method: "POST", body: "{}" })).rejects.toMatchObject({ status: 423 });
  expect(fetch).not.toHaveBeenCalled();
  setWorkspaceLocked(false);
  expect(fetch).not.toHaveBeenCalled();
});
it("a fresh login clears a stale workspaceLocked flag left over from a previous session", async () => {
  // Regression: leaving a locked workspace without explicitly unlocking or
  // logging out (e.g. navigating straight to /login) must not leave every
  // subsequent call, including the post-login refresh, rejecting as if still locked.
  setWorkspaceLocked(true);
  const session = { locked: false, expires_at: Date.now() / 1000 + 900, server_time: Date.now() / 1000 };
  const fetch = vi.fn(async (path) => {
    if (path.endsWith("/csrf/")) return response(200, { csrfToken: "test-token" });
    if (path.endsWith("/login/")) return response(200, { authenticated: true, access_token: "fresh-token", access_expires_in: 180, session });
    if (path.endsWith("/refresh/")) return response(200, { authenticated: true, access_token: "rotated-token", access_expires_in: 180, session });
    return response(200, {});
  });
  vi.stubGlobal("fetch", fetch);
  await api("/api/v1/auth/login/", { method: "POST", body: "{}" });
  await expect(api("/api/v1/auth/refresh/", { method: "POST" })).resolves.toMatchObject({ authenticated: true });
});
afterEach(() => {
  vi.unstubAllGlobals();
  resetCsrfToken();
  setActiveOrganization(null);
  setWorkspaceLocked(false);
  clearAccessToken();
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


it("binds business requests to the rendered organization, excluding account selection", async () => {
  const fetch = vi.fn(async () => response(200, []));
  vi.stubGlobal("fetch", fetch);
  setActiveOrganization(42);
  await api("/api/v1/catalog/products/");
  expect(fetch.mock.calls[0][1].headers["X-Organization-ID"]).toBe("42");
  await api("/api/v1/tenancy/organizations/");
  expect(fetch.mock.calls[1][1].headers).toBeUndefined();
});
it("sends a write once more with a fresh token when the short-lived token expired (the server did not run it)", async () => {
  resetCsrfToken();
  const session = { locked: false, idle_deadline: new Date(Date.now() + 600000).toISOString(), server_time: new Date().toISOString() };
  let created = 0;
  const fetch = vi.fn(async (path, options = {}) => {
    if (path.endsWith("/csrf/")) return response(200, { csrfToken: "csrf" });
    if (path.endsWith("/refresh/")) return response(200, { authenticated: true, access_token: "fresh-token", access_expires_in: 180, session });
    if (options.headers?.Authorization === "Bearer fresh-token") { created += 1; return response(201, { id: 9 }); }
    return response(401, { code: "token_expired", detail: "Sign in again or refresh your session." });
  });
  vi.stubGlobal("fetch", fetch);
  await expect(api("/api/v1/tenancy/create/", { method: "POST", body: "{}" })).resolves.toEqual({ id: 9 });
  expect(created).toBe(1);
  expect(fetch.mock.calls.filter(([path]) => path === "/api/v1/tenancy/create/")).toHaveLength(2);
});
it("says plainly that the server can't be reached when it sends back nothing or is off", async () => {
  resetCsrfToken();
  const empty = { status: 500, ok: false, json: async () => { throw new SyntaxError("Unexpected end of JSON input"); } };
  vi.stubGlobal("fetch", vi.fn(async () => empty));
  await expect(api("/api/v1/auth/login/", { method: "POST", body: "{}" })).rejects.toThrow(SERVER_UNREACHABLE);
  resetCsrfToken();
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  await expect(api("/api/v1/auth/login/", { method: "POST", body: "{}" })).rejects.toThrow(SERVER_UNREACHABLE);
});
it("fetches a fresh security token and retries a sign-in the server refused for a stale one", async () => {
  resetCsrfToken();
  let token = 0;
  let logins = 0;
  const fetch = vi.fn(async (path, options) => {
    if (path.endsWith("/csrf/")) return response(200, { csrfToken: `token-${++token}` });
    logins += 1;
    return options.headers["X-CSRFToken"] === "token-1"
      ? response(403, { detail: "CSRF Failed: CSRF token from the 'X-Csrftoken' HTTP header incorrect." })
      : response(400, { detail: "Invalid credentials." });
  });
  vi.stubGlobal("fetch", fetch);
  await expect(api("/api/v1/auth/login/", { method: "POST", body: "{}" })).rejects.toThrow("Invalid credentials.");
  expect(logins).toBe(2);
  resetCsrfToken();
});

it("sends every backend request to VITE_API_BASE_URL when the build sets it, with credentials and the CSRF token", async () => {
  vi.resetModules();
  vi.stubEnv("VITE_API_BASE_URL", "https://api.dukaflow.co.ke/");
  try {
    const client = await import("./client");
    const fetch = vi.fn(async (url) => response(200, url.endsWith("/csrf/") ? { csrfToken: "t" } : { authenticated: true }));
    vi.stubGlobal("fetch", fetch);
    await client.api("/api/v1/auth/login/", { method: "POST", body: "{}" });
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "https://api.dukaflow.co.ke/api/v1/auth/csrf/", "https://api.dukaflow.co.ke/api/v1/auth/login/",
    ]);
    expect(fetch.mock.calls[1][1]).toMatchObject({ credentials: "include", headers: { "X-CSRFToken": "t" } });
    expect(client.apiUrl("/media/products/a.webp")).toBe("https://api.dukaflow.co.ke/media/products/a.webp");
    expect(client.apiUrl("/assets/logo.png")).toBe("/assets/logo.png");
    expect(client.apiUrl("https://cdn.example.com/a.png")).toBe("https://cdn.example.com/a.png");
  } finally {
    vi.unstubAllEnvs();
    vi.resetModules();
  }
});

it("keeps backend requests relative when VITE_API_BASE_URL is not set (local development)", async () => {
  const { apiUrl } = await import("./client");
  expect(apiUrl("/api/v1/auth/me/")).toBe("/api/v1/auth/me/");
});
it("sends a save again after unlocking when the session could not be renewed", async () => {
  resetCsrfToken();
  setWorkspaceLocked(false);
  let tokenExpired = true;
  const fetch = vi.fn(async (path) => {
    if (path.endsWith("/csrf/")) return response(200, { csrfToken: "csrf" });
    if (path.endsWith("/refresh/")) return response(401, { detail: "Please sign in again.", code: "session_expired" });
    if (tokenExpired) return response(401, { detail: "Token expired.", code: "token_expired" });
    return response(200, { saved: true });
  });
  vi.stubGlobal("fetch", fetch);
  // The workspace locks (as AuthContext does) when the session has ended; unlocking signs in again.
  const lockScreen = () => setWorkspaceLocked(true);
  window.addEventListener("session-expired", lockScreen, { once: true });
  const saving = api("/api/v1/inventory/receipts/", { method: "POST", body: "{}" });
  await vi.waitFor(() => expect(fetch.mock.calls.some(([path]) => path.endsWith("/refresh/"))).toBe(true));
  await new Promise(resolve => setTimeout(resolve, 0));
  tokenExpired = false;
  setWorkspaceLocked(false);
  await expect(saving).resolves.toEqual({ saved: true });
});
