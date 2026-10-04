import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthContext";
import { api, setWorkspaceLocked } from "../api/client";
vi.mock("../api/client", async original => ({ ...(await original()), api: vi.fn() }));
let deadline;
const identity = () => ({ authenticated: true, id: 5, username: "long-business-owner", organization: { id: 7, name: "Shop" }, permissions: [], memberships: [],
  session: { expires_at: deadline, server_time: Date.now() / 1000, locked: Date.now() / 1000 >= deadline, idle_timeout: 300, warning_seconds: 0 } });
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-21T10:00:00Z"));
  deadline = Date.now() / 1000 + 300;
  api.mockImplementation(async (path, options) => {
    if (path.endsWith("/activity/")) deadline = Date.now() / 1000 + 300;
    if (path.endsWith("/unlock/")) {
      if (JSON.parse(options.body).password !== "correct") throw new Error("Incorrect password. Please try again.");
      deadline = Date.now() / 1000 + 300;
    }
    return identity();
  });
});
afterEach(() => { cleanup(); setWorkspaceLocked(false); vi.useRealTimers(); vi.clearAllMocks(); });
async function mount() {
  // The idle lock only applies within the authenticated /admin workspace.
  await act(async () => { render(<MemoryRouter initialEntries={["/admin/dashboard"]}><AuthProvider><label>Unsaved notes<input defaultValue="Draft receipt" /></label></AuthProvider></MemoryRouter>); });
}
async function advance(milliseconds) { await act(async () => { vi.advanceTimersByTime(milliseconds); }); }
it("locks after five minutes, obscures amounts and preserves a private form", async () => {
  await mount();
  await advance(299000);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.pointerMove(window); // Synthetic input is not activity.
  await advance(1000);
  expect(screen.getByRole("dialog")).toHaveTextContent("Workspace locked");
  expect(document.querySelector(".sessionWorkspace")).toHaveStyle({ visibility: "hidden" });
  expect(document.querySelector(".sessionWorkspace")).toHaveAttribute("inert");
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "correct" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Unlock" })); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Unsaved notes")).toHaveValue("Draft receipt");
});
it("incorrect passwords leave the workspace locked and clear the password field", async () => {
  await mount(); await advance(300000);
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "wrong" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Unlock" })); });
  expect(screen.getByRole("alert")).toHaveTextContent("Incorrect password");
  expect(screen.getByLabelText("Password", { exact: true })).toHaveValue("");
  expect(document.querySelector(".sessionWorkspace")).toHaveAttribute("inert");
});
it("uses elapsed time when a sleeping tab wakes and verifies other-tab unlocks", async () => {
  await mount();
  vi.setSystemTime(new Date("2026-09-21T10:06:00Z"));
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(screen.getByRole("dialog")).toHaveTextContent("Workspace locked");
  deadline = Date.now() / 1000 + 300;
  await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key: "workspace-session-event", newValue: JSON.stringify({ action: "sync" }) })); await Promise.resolve(); });
  // An activity response from before locking must never unlock a tab.
  expect(screen.getByRole("dialog")).toHaveTextContent("Workspace locked");
  await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key: "workspace-session-event", newValue: JSON.stringify({ action: "unlocked" }) })); await Promise.resolve(); await Promise.resolve(); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("never shows the idle lock on public routes, even with a long-idle authenticated session", async () => {
  await act(async () => { render(<MemoryRouter initialEntries={["/"]}><AuthProvider><label>Public homepage<input defaultValue="anyone can see this" /></label></AuthProvider></MemoryRouter>); });
  await advance(600000); // Ten idle minutes, well past the five-minute deadline.
  fireEvent.pointerMove(window);
  await advance(1000);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.querySelector(".sessionWorkspace")).not.toHaveStyle({ visibility: "hidden" });
  expect(document.querySelector(".sessionWorkspace")).not.toHaveAttribute("inert");
});
it("a fresh password login replaces a stale locked session instead of showing the lock screen", async () => {
  const { Routes, Route } = await import("react-router-dom");
  const { useAuthForm } = await import("../../modules/auth/useAuthForm");
  function Login() { const { submit } = useAuthForm(); return <form onSubmit={submit}><button>Sign in</button></form>; }
  deadline = Date.now() / 1000 - 60; // Yesterday's session on this browser went idle and locked.
  await act(async () => { render(<MemoryRouter initialEntries={["/login"]}><AuthProvider><Routes>
    <Route path="/login" element={<Login />} /><Route path="/admin/dashboard" element={<p>Dashboard</p>} />
  </Routes></AuthProvider></MemoryRouter>); });
  deadline = Date.now() / 1000 + 300; // Signing in with a password starts a new session.
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sign in" })); });
  expect(screen.getByText("Dashboard")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
