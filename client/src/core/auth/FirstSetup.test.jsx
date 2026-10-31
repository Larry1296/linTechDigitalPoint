import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({ api: vi.fn() }));
vi.mock("./AuthContext", () => ({ useAuth: vi.fn() }));
import { api } from "../api/client";
import { useAuth } from "./AuthContext";
import { FirstSetup } from "./FirstSetup";

const refresh = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  useAuth.mockReturnValue({ user: { first_name: "Jane", organization: { name: "Corner shop" } }, refresh, logout: vi.fn() });
  api.mockResolvedValue({});
});

const fill = (values) => {
  for (const [label, value] of Object.entries(values)) fireEvent.change(screen.getByLabelText(label), { target: { value } });
};

it("has a new employee choose their own password and lock PIN, then opens the workspace", async () => {
  render(<FirstSetup />);
  expect(screen.getByRole("heading", { name: "Welcome, Jane. Set up your sign-in" })).toBeInTheDocument();
  fill({ "Your new password": "Chosen-by-me-4821", "Your new password again": "Chosen-by-me-4821", "Your lock PIN (4 to 6 numbers)": "48a26", "Your lock PIN again": "4827" });
  expect(screen.getByLabelText("Your lock PIN (4 to 6 numbers)")).toHaveValue("4826");  // numbers only
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save and continue" })); });
  expect(screen.getByText("The two PINs are not the same.")).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
  fill({ "Your lock PIN again": "4826" });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save and continue" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/auth/setup/", { method: "POST", body: JSON.stringify({ new_password: "Chosen-by-me-4821", pin: "4826" }) });
  expect(refresh).toHaveBeenCalled();
});
