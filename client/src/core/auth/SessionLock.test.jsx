import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthContext";
import { api, refreshAccess, setWorkspaceLocked } from "../api/client";
vi.mock("../api/client", async original => ({ ...(await original()), api: vi.fn(), refreshAccess: vi.fn(async () => ({})), accessNeedsRefresh: () => true }));
const TWELVE_HOURS = 12 * 3600;
let deadline;
let lockedByHand;
let pinLength;
const session = () => ({ expires_at: deadline, server_time: Date.now() / 1000, locked: lockedByHand || Date.now() / 1000 >= deadline,
  idle_timeout: 0, warning_seconds: 0, pin_length: lockedByHand && Date.now() / 1000 < deadline ? pinLength : null });
const identity = () => ({ authenticated: true, id: 5, username: "long-business-owner", organization: { id: 7, name: "Shop" }, permissions: [], memberships: [], session: session() });
const wrong = (message) => Object.assign(new Error(message), { status: 400, data: { session: session() } });
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-21T10:00:00Z"));
  deadline = Date.now() / 1000 + TWELVE_HOURS - 600;
  lockedByHand = false;
  pinLength = 4;
  api.mockImplementation(async (path, options) => {
    if (path.endsWith("/auth/lock/")) { lockedByHand = true; return { session: session() }; }
    if (path.endsWith("/login/")) lockedByHand = false;  // a new session
    if (path.endsWith("/unlock/")) {
      const body = JSON.parse(options.body);
      if (body.pin !== undefined) {
        if (body.pin !== "4826") { pinLength = null; throw wrong("Wrong PIN too many times. Enter your password to unlock."); }
      } else if (body.password !== "correct") throw new Error("Incorrect password. Please try again.");
      else deadline = Date.now() / 1000 + TWELVE_HOURS - 600;
      lockedByHand = false;
    }
    return identity();
  });
});
afterEach(() => { cleanup(); setWorkspaceLocked(false); vi.useRealTimers(); vi.clearAllMocks(); });
function LockButton() { const { lock } = useAuth(); return <button type="button" onClick={lock}>Lock workspace</button>; }
async function mount() {
  // The lock only applies within the authenticated /admin workspace.
  await act(async () => { render(<MemoryRouter initialEntries={["/admin/dashboard"]}><AuthProvider>
    <label>Unsaved notes<input defaultValue="Draft receipt" /></label><LockButton />
  </AuthProvider></MemoryRouter>); });
}
async function advance(milliseconds) { await act(async () => { vi.advanceTimersByTime(milliseconds); }); }
it("never locks for being idle, and keeps its token renewed while the page is out of view", async () => {
  await mount();
  Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
  refreshAccess.mockClear();
  await advance(3 * 3600 * 1000);  // three untouched hours, the tab in the background
  Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(refreshAccess).toHaveBeenCalled();
  expect(api).not.toHaveBeenCalledWith("/api/v1/auth/activity/", expect.anything());
});
it("locks only when locked by hand, hides the page and opens with the PIN, keeping a private form", async () => {
  await mount();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Lock workspace" })); });
  expect(screen.getByRole("dialog")).toHaveTextContent("Workspace locked");
  expect(document.querySelector(".sessionWorkspace")).toHaveStyle({ visibility: "hidden" });
  expect(document.querySelector(".sessionWorkspace")).toHaveAttribute("inert");
  await act(async () => { fireEvent.change(screen.getByLabelText("PIN"), { target: { value: "4826" } }); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/v1/auth/unlock/", { method: "POST", body: JSON.stringify({ pin: "4826" }) });
  expect(screen.getByLabelText("Unsaved notes")).toHaveValue("Draft receipt");
});
it("after too many wrong PINs asks for the password, which clears a wrong try", async () => {
  await mount();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Lock workspace" })); });
  await act(async () => { fireEvent.change(screen.getByLabelText("PIN"), { target: { value: "0000" } }); });
  expect(screen.getByRole("alert")).toHaveTextContent("Wrong PIN too many times");
  expect(screen.queryByLabelText("PIN")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "wrong" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Unlock" })); });
  expect(screen.getByRole("alert")).toHaveTextContent("Incorrect password");
  expect(screen.getByLabelText("Password", { exact: true })).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "correct" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Unlock" })); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("at the end of its 12 hours asks for the password, also when a sleeping tab wakes", async () => {
  await mount();
  vi.setSystemTime(new Date(deadline * 1000 + 1000));
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(screen.getByRole("dialog")).toHaveTextContent("Workspace locked");
  expect(screen.getByLabelText("Password", { exact: true })).toBeInTheDocument();
  deadline = Date.now() / 1000 + TWELVE_HOURS;  // another tab unlocked it with the password
  lockedByHand = false;
  await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key: "workspace-session-event", newValue: JSON.stringify({ action: "sync" }) })); await Promise.resolve(); });
  // A response from before locking must never unlock a tab.
  expect(screen.getByRole("dialog")).toHaveTextContent("Workspace locked");
  await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key: "workspace-session-event", newValue: JSON.stringify({ action: "unlocked" }) })); await Promise.resolve(); await Promise.resolve(); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("never shows the lock on public routes, even with an ended authenticated session", async () => {
  deadline = Date.now() / 1000 - 60;
  await act(async () => { render(<MemoryRouter initialEntries={["/"]}><AuthProvider><label>Public homepage<input defaultValue="anyone can see this" /></label></AuthProvider></MemoryRouter>); });
  await advance(1000);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.querySelector(".sessionWorkspace")).not.toHaveStyle({ visibility: "hidden" });
  expect(document.querySelector(".sessionWorkspace")).not.toHaveAttribute("inert");
});
it("a fresh password login replaces a stale locked session instead of showing the lock screen", async () => {
  const { Routes, Route } = await import("react-router-dom");
  const { useAuthForm } = await import("../../modules/auth/useAuthForm");
  function Login() { const { submit } = useAuthForm(); return <form onSubmit={submit}><button>Sign in</button></form>; }
  deadline = Date.now() / 1000 - 60; // Yesterday's session on this browser ended.
  await act(async () => { render(<MemoryRouter initialEntries={["/login"]}><AuthProvider><Routes>
    <Route path="/login" element={<Login />} /><Route path="/admin/dashboard" element={<p>Dashboard</p>} />
  </Routes></AuthProvider></MemoryRouter>); });
  deadline = Date.now() / 1000 + TWELVE_HOURS; // Signing in with a password starts a new session.
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sign in" })); });
  expect(screen.getByText("Dashboard")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
