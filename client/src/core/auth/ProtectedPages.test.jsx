import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../api/client", () => ({ api: vi.fn() }));
import { api } from "../api/client";
import { ProtectedPages } from "./ProtectedPages";

const base = { has_password: true, expired: false, unlocked: false, expires_at: "2026-10-19T10:00:00Z", lifetime_days: 7, shortest: 6 };
const page = () => render(<MemoryRouter initialEntries={["/admin/mpesa"]}><Routes>
  <Route element={<ProtectedPages />}><Route path="/admin/mpesa" element={<p>M-Pesa records</p>} /></Route>
</Routes></MemoryRouter>);

beforeEach(() => vi.clearAllMocks());

it("asks for the protected pages password before showing the page", async () => {
  api.mockImplementation(async (path) => path.endsWith("unlock/") ? { protected: { ...base, unlocked: true } } : { protected: base });
  page();
  fireEvent.change(await screen.findByLabelText("Protected pages password"), { target: { value: "vault-2026" } });
  expect(screen.queryByText("M-Pesa records")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  expect(await screen.findByText("M-Pesa records")).toBeInTheDocument();
  expect(JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/auth/protected/unlock/")[1].body)).toEqual({ password: "vault-2026" });
});

it("after a week asks for a new password, proved with the old one", async () => {
  api.mockImplementation(async (path) => path.endsWith("password/") ? { protected: { ...base, unlocked: true } } : { protected: { ...base, expired: true } });
  page();
  expect(await screen.findByRole("heading")).toHaveTextContent("Time for a new protected pages password");
  fireEvent.change(screen.getByLabelText("Your current protected pages password"), { target: { value: "vault-one" } });
  fireEvent.change(screen.getByLabelText("New protected pages password"), { target: { value: "vault-two" } });
  fireEvent.change(screen.getByLabelText("New password again"), { target: { value: "vault-two" } });
  fireEvent.click(screen.getByRole("button", { name: "Save and open" }));
  expect(await screen.findByText("M-Pesa records")).toBeInTheDocument();
  expect(JSON.parse(api.mock.calls.find(([p]) => p === "/api/v1/auth/protected/password/")[1].body)).toEqual({ proof: "vault-one", new_password: "vault-two" });
});
