let csrfToken;
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
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    };
  }
  const response = await fetch(path, { credentials: "include", ...options });
  if (response.status === 204) return undefined;
  const data = await response
    .json()
    .catch(() => ({ detail: "Request failed." }));
  if (!response.ok)
    throw new ApiError(
      response.status,
      data.detail || Object.values(data).flat().join(" ") || "Request failed.",
    );
  return data;
}
