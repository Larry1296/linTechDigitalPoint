import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { LoginPage } from "./AuthPages";
import { api, ApiError } from "../../core/api/client";

vi.mock("../../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ signedIn: vi.fn() }) }));
vi.mock("../platform/PlatformContext", () => ({ usePlatform: () => ({ name: "LinTech" }) }));

it("shows a failed sign-in as a clear error below the Sign in button", async () => {
  api.mockRejectedValue(new ApiError(400, "Invalid credentials."));
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Username or email"), { target: { value: "larry" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sign in" })); });
  const alert = screen.getByRole("alert");
  expect(alert).toHaveClass("formNoticeError");
  expect(alert).toHaveTextContent("Could not sign in. Invalid credentials.");
  expect(alert.previousElementSibling).toBe(screen.getByRole("button", { name: "Sign in" }));
});
