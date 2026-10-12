import { announceDataChanged } from "../data/liveRefresh";
import { mutationFinished, mutationStarted } from "../ui/outcome";
let accessToken;
let accessExpiresAt = 0;
let refreshFlight;
let activeBranch;
export function setActiveBranch(id) { activeBranch = id == null ? undefined : String(id); }
export function clearAccessToken() { accessToken = undefined; accessExpiresAt = 0; }
export function accessNeedsRefresh() { return !!accessToken && Date.now() >= accessExpiresAt - 30000; }
function acceptAccess(data) {
  if (!data.access_token) return;
  accessToken = data.access_token;
  accessExpiresAt = Date.now() + data.access_expires_in * 1000;
  // The token remains module-private. Events never carry credentials.
}
export async function refreshAccess() {
  if (workspaceLocked) throw new ApiError(423, SESSION_EXPIRED_MESSAGE);
  if (!refreshFlight) {
    const rotate = async () => {
      if (workspaceLocked) throw new ApiError(423, SESSION_EXPIRED_MESSAGE);
      const csrf = await getCsrfToken();
      const response = await send('/api/v1/auth/refresh/', { method:'POST', credentials:'include', headers:{ 'X-CSRFToken':csrf } });
      const data = await readJson(response);
      if (response.status === 423) { notifyLocked(data.session); throw new ApiError(423, data.detail); }
      if (!response.ok) { if (response.status === 401) window.dispatchEvent(new Event('session-expired')); throw new ApiError(response.status, data.detail); }
      if (!workspaceLocked) acceptAccess(data);
      const { access_token: omittedToken, ...identity } = data;
      void omittedToken;
      return identity;
    };
    // Same-origin tabs serialize rotations without sharing any credential.
    refreshFlight = (navigator.locks ? navigator.locks.request('lintech-refresh', rotate) : rotate())
      .finally(() => { refreshFlight = undefined; });
  }
  return refreshFlight;
}
// What the person sees when the server sends nothing usable back (it is off, restarting or the connection dropped),
// instead of a browser error such as "Unexpected end of JSON input".
export const SERVER_UNREACHABLE = "Can't reach the LinTech server right now. Check your internet connection, or that the server is running, then try again.";
async function send(path, options) {
  try {
    return await fetch(path, options);
  } catch (err) {
    if (err?.name === "AbortError" || err?.name === "TimeoutError") throw err;
    throw new ApiError(0, SERVER_UNREACHABLE);
  }
}
async function readJson(response) {
  try {
    return await response.json();
  } catch {
    if (response.ok) return {};
    throw new ApiError(response.status, SERVER_UNREACHABLE);
  }
}
let csrfToken;
let activeOrganization;
let workspaceLocked = false;
let sessionCheck;
let expiryNotified = false;
let csrfRequest;
export const SESSION_EXPIRED_MESSAGE = "Your session expired. Enter your password to unlock.";
export function setActiveOrganization(id) {
  activeOrganization = id == null ? undefined : String(id);
}
export function setWorkspaceLocked(locked) {
  workspaceLocked = locked;
  if (locked) clearAccessToken();
  if (!locked) window.dispatchEvent(new Event("session-unlocked"));
}
function notifyLocked(session) {
  if (!workspaceLocked) {
    workspaceLocked = true;
    clearAccessToken();
    window.dispatchEvent(new CustomEvent("session-locked", { detail: session }));
  }
}
async function getCsrfToken() {
  if (csrfToken) return csrfToken;
  if (!csrfRequest) {
    csrfRequest = send("/api/v1/auth/csrf/", { credentials: "include" })
      .then(readJson)
      .then(data => { csrfToken = data.csrfToken; return csrfToken; })
      .finally(() => { csrfRequest = undefined; });
  }
  return csrfRequest;
}
async function checkExpiredSession() {
  if (expiryNotified) return "expired";
  if (!sessionCheck) {
    sessionCheck = fetch("/api/v1/auth/me/", { credentials: "include", signal: AbortSignal.timeout(5000) })
      .then(async response => response.ok ? response.json() : null)
      .catch(() => null)
      .finally(() => { sessionCheck = undefined; });
  }
  const data = await sessionCheck;
  if (data?.session?.locked) { notifyLocked(data.session); return "locked"; }
  if (data?.authenticated === false) {
    if (!expiryNotified) {
      expiryNotified = true;
      csrfToken = undefined;
      window.dispatchEvent(new Event("session-expired"));
    }
    return "expired";
  }
  return "active";
}
export function resetCsrfToken() {
  csrfToken = undefined;
  csrfRequest = undefined;
  sessionCheck = undefined;
  expiryNotified = false;
}
export class ApiError extends Error {
  status;
  data;
  // ``data`` keeps the server's structured error (e.g. field errors or a "below_cost" list).
  constructor(status, message, data = undefined) { super(message); this.status = status; this.data = data; }
}
function waitForUnlock(signal) {
  if (!workspaceLocked) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      window.removeEventListener("session-unlocked", unlocked);
      signal?.removeEventListener("abort", aborted);
      window.removeEventListener("session-signed-out", signedOut);
    };
    const unlocked = () => { cleanup(); resolve(); };
    const aborted = () => { cleanup(); reject(new DOMException("Request aborted", "AbortError")); };
    const signedOut = () => { cleanup(); reject(new ApiError(401, "Signed out.")); };
    if (signal?.aborted) { aborted(); return; }
    window.addEventListener("session-unlocked", unlocked, { once: true });
    window.addEventListener("session-signed-out", signedOut, { once: true });
    signal?.addEventListener("abort", aborted, { once: true });
  });
}
// Every request; a save (a changing request after a form is submitted) also ends in a full-screen outcome (see outcome.js).
export async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const tracked = !["GET", "HEAD", "OPTIONS"].includes(method) && mutationStarted(path);
  try {
    const data = await request(path, options);
    if (tracked) mutationFinished(true);
    return data;
  } catch (err) {
    if (tracked) mutationFinished(false, err.message);
    throw err;
  }
}
async function request(path, options = {}, retried = false, coordinated = false) {
  if (!coordinated && navigator.locks && ['/api/v1/auth/lock/', '/api/v1/auth/unlock/', '/api/v1/auth/logout/'].includes(path)) {
    return navigator.locks.request('lintech-refresh', () => request(path, options, retried, true));
  }
  if (path === "/api/v1/auth/refresh/") return refreshAccess();
  const requestOptions = { ...options };
  const method = (requestOptions.method || "GET").toUpperCase();
  const safe = ["GET", "HEAD", "OPTIONS"].includes(method);
  const protectedPath = path.startsWith("/api/v1/") && !path.startsWith("/api/v1/auth/") && path !== "/api/v1/tenancy/platform/";
  if (workspaceLocked && protectedPath) {
    if (!safe) throw new ApiError(423, SESSION_EXPIRED_MESSAGE);
    await waitForUnlock(requestOptions.signal);
  }
  if (!safe) {
    await getCsrfToken();
    requestOptions.headers = { ...requestOptions.headers, "X-CSRFToken": csrfToken,
      ...(requestOptions.body instanceof FormData ? {} : { "Content-Type": "application/json" }) };
  }
  if (activeOrganization && protectedPath && !path.startsWith("/api/v1/tenancy/")) {
    requestOptions.headers = { ...requestOptions.headers, "X-Organization-ID": activeOrganization };
  }
  if (activeBranch && protectedPath && !path.startsWith('/api/v1/tenancy/')) requestOptions.headers = { ...requestOptions.headers, 'X-Branch-ID':activeBranch };
  if (accessToken) requestOptions.headers = { ...requestOptions.headers, Authorization:`Bearer ${accessToken}` };
  const response = await send(path, { credentials: "include", ...requestOptions });
  // A saved change means figures elsewhere may be out of date: let open pages refresh themselves.
  if (response.ok && !safe && protectedPath) announceDataChanged(path);
  if (response.status === 204) return undefined;
  const data = await response.json().catch(() => ({ detail: response.status >= 500 ? SERVER_UNREACHABLE : "Request failed." }));
  if (!response.ok) {
    // The server refuses an expired token before running the request, so any request (a sale, creating a business)
    // is safe to send once more with a fresh token.
    if (response.status === 401 && data.code === 'token_expired' && protectedPath && !retried && !workspaceLocked) {
      await refreshAccess();
      return request(path, options, true);
    }
    if (response.status === 423 && data.code === "session_locked") {
      notifyLocked(data.session);
      if (safe && protectedPath && !retried) {
        await waitForUnlock(requestOptions.signal);
        return request(path, options, true);
      }
      throw new ApiError(423, data.detail || SESSION_EXPIRED_MESSAGE);
    }
    // The security token changes when someone signs in or out (also in another tab). A refused token is fetched
    // afresh and the request sent once more, so a corrected sign-in is not stuck failing until the page reloads.
    if (response.status === 403 && !safe && !retried && /CSRF/i.test(data.detail || "")) {
      resetCsrfToken();
      return request(path, options, true);
    }
    if ([401, 403].includes(response.status) && protectedPath) {
      const state = await checkExpiredSession();
      if (state === "expired") throw new ApiError(response.status, SESSION_EXPIRED_MESSAGE);
      if (state === "locked") {
        if (safe && !retried) { await waitForUnlock(requestOptions.signal); return request(path, options, true); }
        throw new ApiError(423, SESSION_EXPIRED_MESSAGE);
      }
    }
    // M-Pesa and investments need the protected pages password too: let the page ask for it.
    if (response.status === 403 && data.code === "protected_locked") window.dispatchEvent(new Event("protected-locked"));
    throw new ApiError(response.status, data.detail || Object.values(data).flat().join(" ") || "Request failed.", data);
  }
  if (path.startsWith("/api/v1/auth/") && data.authenticated) expiryNotified = false;
  if (workspaceLocked && protectedPath) throw new ApiError(423, SESSION_EXPIRED_MESSAGE);
  // A fresh, unlocked device session (login/register/unlock) always supersedes a
  // stale workspaceLocked flag left over from a previous session in this tab —
  // otherwise refreshAccess() rejects every call right after a brand-new login.
  // A fresh, unlocked device session (login/register/unlock) always supersedes a
  // stale workspaceLocked flag left over from a previous session in this tab —
  // otherwise refreshAccess() rejects every call right after a brand-new login.
  if (data.access_token && !data.session?.locked) setWorkspaceLocked(false);
  acceptAccess(data);
  if (data.access_token) { const { access_token: omittedToken, ...identity } = data; void omittedToken; return identity; }
  return data;
}

export async function privateBlob(path, signal) {
  if (!path.startsWith('/media/')) throw new ApiError(400, 'Invalid private media path.');
  if (workspaceLocked) await waitForUnlock(signal);
  if (!accessToken || accessNeedsRefresh()) await refreshAccess();
  const response = await fetch(path, { credentials:'include', signal, headers:{ Authorization:`Bearer ${accessToken}` } });
  if (!response.ok || workspaceLocked) throw new ApiError(response.status, 'Image unavailable.');
  return response.blob();
}

// A streamed POST (server-sent events, e.g. the business assistant), with the same credentials and business/branch
// headers as api(). Returns the open Response for the caller to read; errors are thrown like api() throws them.
export async function apiStream(path, body, signal) {
  if (workspaceLocked) throw new ApiError(423, SESSION_EXPIRED_MESSAGE);
  if (!accessToken || accessNeedsRefresh()) await refreshAccess();
  await getCsrfToken();
  const send = () => {
    const headers = { "Content-Type": "application/json", "X-CSRFToken": csrfToken, Authorization: `Bearer ${accessToken}` };
    if (activeOrganization) headers["X-Organization-ID"] = activeOrganization;
    if (activeBranch) headers["X-Branch-ID"] = activeBranch;
    return fetch(path, { method: "POST", credentials: "include", signal, headers, body: JSON.stringify(body) });
  };
  let response = await send();
  if (response.status === 401) {
    const data = await response.clone().json().catch(() => ({}));
    if (data.code === "token_expired") { await refreshAccess(); response = await send(); }
  }
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.detail || "The request failed.", data);
  }
  return response;
}

// A file from the API (e.g. a PDF report), sent with the same credentials and business/branch headers as api().
export async function apiBlob(path, signal) {
  if (workspaceLocked) await waitForUnlock(signal);
  if (!accessToken || accessNeedsRefresh()) await refreshAccess();
  const headers = { Authorization: `Bearer ${accessToken}` };
  if (activeOrganization) headers["X-Organization-ID"] = activeOrganization;
  if (activeBranch) headers["X-Branch-ID"] = activeBranch;
  const response = await fetch(path, { credentials: "include", signal, headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.detail || "The file could not be downloaded.");
  }
  return response.blob();
}
