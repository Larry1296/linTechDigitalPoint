import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { RegisterPage } from "./Onboarding";
import { api } from "../../core/api/client";

vi.mock("../../core/api/client", () => ({ api: vi.fn(async () => ({})), resetCsrfToken: vi.fn() }));
const signedIn = vi.fn();
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ signedIn }) }));
beforeEach(() => vi.clearAllMocks());

const fill = (label, value) => fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
const details = (confirm) => {
  fill("First name", "Wanjiru"); fill("Last name", "Kamau"); fill("Phone number", "0712 345 678");
  fill("Email", "wanjiru@example.test"); fill("Username", "wanjiru");
  fill("Password", "Kiandas-pass-2026"); fill("Confirm password", confirm);
};

it("collects the owner's name, phone, email and a confirmed password", async () => {
  render(<MemoryRouter><RegisterPage /></MemoryRouter>);
  details("Kiandas-pass-2026");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create account and continue" })); });
  const [path, options] = api.mock.calls[0];
  expect(path).toBe("/api/v1/tenancy/register/");
  expect(JSON.parse(options.body)).toEqual({ first_name: "Wanjiru", last_name: "Kamau", phone: "0712 345 678", email: "wanjiru@example.test",
    username: "wanjiru", password: "Kiandas-pass-2026", password_confirm: "Kiandas-pass-2026" });
  expect(signedIn).toHaveBeenCalled();
});

it("stops before sending when the two passwords differ", async () => {
  render(<MemoryRouter><RegisterPage /></MemoryRouter>);
  details("Something-else-1");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Create account and continue" })); });
  expect(api).not.toHaveBeenCalled();
  expect(screen.getByText("The two passwords do not match.")).toBeInTheDocument();
});
