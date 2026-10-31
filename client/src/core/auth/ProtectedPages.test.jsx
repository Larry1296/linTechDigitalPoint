import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("../api/client", () => ({ api: vi.fn() }));
import { api } from "../api/client";
import { PRIVATE_IDLE_MS, ProtectedPages } from "./ProtectedPages";

const pages = (mpesa = {}, investments = {}) => ({
  mpesa: { label: "M-Pesa", own_pin: false, pin_length: 4, unlocked: false, ...mpesa },
  investments: { label: "Investments", own_pin: false, pin_length: 4, unlocked: false, ...investments },
});
const status = (extra = {}) => ({ has_pin: true, needs_password: false, tries_left: 5, pages: pages(), ...extra });
const page = (path = "/admin/mpesa") => render(<MemoryRouter initialEntries={[path]}><Routes>
  <Route element={<ProtectedPages />}>
    <Route path="/admin/mpesa" element={<p>M-Pesa records</p>} />
    <Route path="/admin/investments" element={<p>Investment records</p>} />
  </Route>
</Routes></MemoryRouter>);
const body = (path) => JSON.parse(api.mock.calls.find(([p]) => p === path)[1].body);

beforeEach(() => { vi.clearAllMocks(); });
afterEach(() => { vi.useRealTimers(); });

it("opens a private page the moment its PIN is typed", async () => {
  api.mockImplementation(async (path) => path.endsWith("unlock/") ? { protected: status({ pages: pages({ unlocked: true }, { unlocked: true }) }) } : { protected: status() });
  page();
  const pin = await screen.findByLabelText("PIN");
  await act(async () => { fireEvent.change(pin, { target: { value: "482" } }); });
  expect(screen.queryByText("M-Pesa records")).toBeNull();
  await act(async () => { fireEvent.change(pin, { target: { value: "4826" } }); });
  expect(await screen.findByText("M-Pesa records")).toBeInTheDocument();
  expect(body("/api/v1/auth/protected/unlock/")).toEqual({ page: "mpesa", pin: "4826" });
});

it("says a page has its own PIN, clears a wrong one and keeps the tries count", async () => {
  api.mockImplementation(async (path) => {
    if (path.endsWith("unlock/")) throw Object.assign(new Error("Wrong PIN. 4 tries left."), { data: { code: "wrong_pin", protected: status({ tries_left: 4 }) } });
    return { protected: status({ pages: pages({}, { own_pin: true, pin_length: 6 }) }) };
  });
  page("/admin/investments");
  expect(await screen.findByText("Investments has a PIN of its own.")).toBeInTheDocument();
  const pin = screen.getByLabelText("PIN");
  await act(async () => { fireEvent.change(pin, { target: { value: "111111" } }); });
  expect(await screen.findByText("Wrong PIN. 4 tries left.")).toBeInTheDocument();
  expect(pin).toHaveValue("");
});

it("asks for the sign-in password after too many wrong PINs", async () => {
  api.mockImplementation(async (path) => path.endsWith("unlock/") ? { protected: status({ pages: pages({ unlocked: true }) }) } : { protected: status({ needs_password: true, tries_left: 0 }) });
  page();
  expect(await screen.findByText(/Too many wrong PINs/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Your sign-in password"), { target: { value: "Sign-in-1" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Open" })); });
  expect(await screen.findByText("M-Pesa records")).toBeInTheDocument();
  expect(body("/api/v1/auth/protected/unlock/")).toEqual({ page: "mpesa", password: "Sign-in-1" });
});

it("sets the lock PIN the first time, then opens the page with it", async () => {
  api.mockImplementation(async (path) => {
    if (path.endsWith("unlock/")) return { protected: status({ pages: pages({ unlocked: true }) }) };
    if (path.endsWith("lock-pin/")) return {};
    return { protected: status({ has_pin: false }) };
  });
  page();
  expect(await screen.findByRole("heading", { name: "Set your lock PIN" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Your sign-in password"), { target: { value: "Sign-in-1" } });
  fireEvent.change(screen.getByLabelText("New PIN (4 to 6 digits)"), { target: { value: "4826" } });
  fireEvent.change(screen.getByLabelText("New PIN again"), { target: { value: "4826" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save and open" })); });
  expect(await screen.findByText("M-Pesa records")).toBeInTheDocument();
  expect(body("/api/v1/auth/lock-pin/")).toEqual({ password: "Sign-in-1", pin: "4826" });
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
