let csrfToken: string | undefined;
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (!csrfToken) {
      const r = await fetch("/api/v1/auth/csrf/", { credentials: "include" });
      csrfToken = (await r.json()).csrfToken;
    }
    options.headers = {
      ...options.headers,
      "X-CSRFToken": csrfToken!,
      "Content-Type": "application/json",
    };
  }
  const response = await fetch(path, { credentials: "include", ...options });
  if (response.status === 204) return undefined as T;
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
