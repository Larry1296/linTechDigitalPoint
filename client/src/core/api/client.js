let csrfToken;
export const SESSION_EXPIRED_MESSAGE =
  "Your session expired. Please sign in again";
let sessionCheck;
let expiryNotified = false;

async function checkExpiredSession() {
  if (!sessionCheck) {
    sessionCheck = fetch("/api/v1/auth/me/", {
      credentials: "include",
      signal: AbortSignal.timeout(5000),
    })
      .then(
        async (response) =>
          response.ok && (await response.json()).authenticated === false,
      )
      .catch(() => false)
      .finally(() => {
        sessionCheck = undefined;
      });
  }
  const expired = await sessionCheck;
  if (expired && !expiryNotified) {
    expiryNotified = true;
    resetCsrfToken();
    window.dispatchEvent(new Event("session-expired"));
  }
  return expired;
}
export function resetCsrfToken() {
  csrfToken = undefined;
}
export class ApiError extends Error {
  status;
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
export async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (!csrfToken) {
      const r = await fetch("/api/v1/auth/csrf/", { credentials: "include" });
      csrfToken = (await r.json()).csrfToken;
    }
    options.headers = {
      ...options.headers,
      "X-CSRFToken": csrfToken,
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
    };
  }
  const response = await fetch(path, { credentials: "include", ...options });
  if (response.status === 204) return undefined;
  const data = await response
    .json()
    .catch(() => ({ detail: "Request failed." }));
  if (!response.ok) {
    if (
      [401, 403].includes(response.status) &&
      (!path.startsWith("/api/v1/auth/") || path === "/api/v1/auth/logout/") &&
      (await checkExpiredSession())
    ) {
      throw new ApiError(response.status, SESSION_EXPIRED_MESSAGE);
    }
    throw new ApiError(
      response.status,
      data.detail || Object.values(data).flat().join(" ") || "Request failed.",
    );
  }
  if (path.startsWith("/api/v1/auth/") && data.authenticated)
    expiryNotified = false;
  return data;
}
