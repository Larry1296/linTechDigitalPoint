import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("../api/client", () => ({ api: vi.fn() }));
import { api } from "../api/client";
import { PRIVATE_IDLE_MS, ProtectedPages } from "./ProtectedPages";

const pages = (mpesa = {}, investments = {}) => ({
  mpesa: { label: "M-Pesa", allowed: true, pin_set: true, pin_length: 4, unlocked: false, ...mpesa },
  investments: { label: "Investments", allowed: true, pin_set: true, pin_length: 6, unlocked: false, ...investments },
});
const status = (extra = {}) => ({ is_owner: true, blocked_until: null, tries_left: 5, pages: pages(), ...extra });
const page = (path = "/admin/mpesa") => render(<MemoryRouter initialEntries={[path]}><Routes>
  <Route element={<ProtectedPages />}>
    <Route path="/admin/mpesa" element={<p>M-Pesa records</p>} />
    <Route path="/admin/investments" element={<p>Investment records</p>} />
  </Route>
</Routes></MemoryRouter>);
const body = (path) => JSON.parse(api.mock.calls.find(([p]) => p === path)[1].body);

beforeEach(() => { vi.clearAllMocks(); });
afterEach(() => { vi.useRealTimers(); });

it("opens a private page the moment its own PIN is typed", async () => {
  api.mockImplementation(async (path) => path.endsWith("unlock/") ? { protected: status({ pages: pages({ unlocked: true }) }) } : { protected: status() });
  page();
  expect(await screen.findByRole("heading", { name: "Enter the M-Pesa PIN" })).toBeInTheDocument();
  const pin = screen.getByLabelText("PIN");
  await act(async () => { fireEvent.change(pin, { target: { value: "482" } }); });
  expect(screen.queryByText("M-Pesa records")).toBeNull();
  await act(async () => { fireEvent.change(pin, { target: { value: "4826" } }); });
  expect(await screen.findByText("M-Pesa records")).toBeInTheDocument();
  expect(body("/api/v1/auth/protected/unlock/")).toEqual({ page: "mpesa", pin: "4826" });
});

it("clears a wrong PIN, never offers the sign-in password, and tells staff to ask the owner", async () => {
  api.mockImplementation(async (path) => {
    if (path.endsWith("unlock/")) throw Object.assign(new Error("Wrong PIN. 4 tries left."), { data: { code: "wrong_pin", protected: status({ is_owner: false, tries_left: 4 }) } });
    return { protected: status({ is_owner: false }) };
  });
  page();
  const pin = await screen.findByLabelText("PIN");
  await act(async () => { fireEvent.change(pin, { target: { value: "1111" } }); });
  expect(await screen.findByText("Wrong PIN. 4 tries left.")).toBeInTheDocument();
  expect(pin).toHaveValue("");
  expect(screen.queryByLabelText(/sign-in password/)).toBeNull();
  expect(screen.getByText("Forgot it? Ask the business owner to reset it.")).toBeInTheDocument();
});

it("keeps investments closed to anyone but the owner", async () => {
  api.mockImplementation(async () => ({ protected: status({ is_owner: false, pages: pages({}, { allowed: false, pin_length: null }) }) }));
  page("/admin/investments");
  expect(await screen.findByRole("heading", { name: "Investments is for the business owner only" })).toBeInTheDocument();
  expect(screen.queryByLabelText("PIN")).toBeNull();
});

it("waits after too many wrong PINs, and the owner is pointed to Settings to reset it", async () => {
  api.mockImplementation(async () => ({ protected: status({ blocked_until: new Date(Date.now() + 300000).toISOString(), tries_left: 5 }) }));
  page();
  expect(await screen.findByText(/Too many wrong PINs. Wait a few minutes/)).toBeInTheDocument();
  expect(screen.queryByLabelText("PIN")).toBeNull();
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/admin/settings");
});

it("lets the owner set a page's PIN the first time, then opens it; staff are asked to wait for the owner", async () => {
  api.mockImplementation(async (path) => {
    if (path.endsWith("unlock/")) return { protected: status({ pages: pages({ unlocked: true }) }) };
    if (path.endsWith("lock-pin/")) return {};
    return { protected: status({ pages: pages({ pin_set: false, pin_length: null }) }) };
  });
  page();
  expect(await screen.findByRole("heading", { name: "Set the M-Pesa PIN" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Your sign-in password"), { target: { value: "Sign-in-1" } });
  fireEvent.change(screen.getByLabelText("M-Pesa PIN (4 to 6 numbers)"), { target: { value: "4826" } });
  fireEvent.change(screen.getByLabelText("The PIN again"), { target: { value: "4826" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save and open" })); });
  expect(await screen.findByText("M-Pesa records")).toBeInTheDocument();
  expect(body("/api/v1/auth/lock-pin/")).toEqual({ page: "mpesa", password: "Sign-in-1", pin: "4826" });
});

it("tells staff the owner has not set a page's PIN yet", async () => {
  api.mockImplementation(async () => ({ protected: status({ is_owner: false, pages: pages({ pin_set: false, pin_length: null }) }) }));
  page();
  expect(await screen.findByRole("heading", { name: "M-Pesa has no PIN yet" })).toBeInTheDocument();
  expect(screen.getByText(/Ask the business owner to set it/)).toBeInTheDocument();
});

it("locks an open private page after five minutes untouched", async () => {
  // Time moves only when the test moves it, and nothing waits on the real clock, so a busy machine cannot make it fail.
  vi.useFakeTimers();
  let open = true;
  api.mockImplementation(async (path) => {
    if (path.endsWith("protected/lock/")) open = false;
    return { protected: status({ pages: pages({ unlocked: open }) }) };
  });
  page();
  await act(async () => {});
  expect(screen.getByText("M-Pesa records")).toBeInTheDocument();
  await act(async () => { vi.advanceTimersByTime(PRIVATE_IDLE_MS - 10000); });
  fireEvent.keyDown(window, { key: "a" });  // synthetic: not a person
  expect(screen.getByText("M-Pesa records")).toBeInTheDocument();
  await act(async () => { vi.advanceTimersByTime(15000); });
  await act(async () => {});
  expect(screen.getByLabelText("PIN")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/v1/auth/protected/lock/", { method: "POST" });
});

it("keeps letters out of a new PIN as it is typed", async () => {
  api.mockImplementation(async () => ({ protected: status({ pages: pages({ pin_set: false, pin_length: null }) }) }));
  page();
  const pin = await screen.findByLabelText("M-Pesa PIN (4 to 6 numbers)");
  fireEvent.change(pin, { target: { value: "48ab26" } });
  expect(pin).toHaveValue("4826");
});
