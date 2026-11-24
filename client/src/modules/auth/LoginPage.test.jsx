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

it("signs in with the fingerprint or face first where it is on here, and keeps the password as another choice", async () => {
  const { rememberKey } = await import("../../core/auth/biometric");
  rememberKey(5, "key-5", "larry");
  window.PublicKeyCredential = { isUserVerifyingPlatformAuthenticatorAvailable: async () => true };
  // The key was removed from another device: the page forgets it and asks for the password.
  api.mockRejectedValue(new ApiError(400, "Fingerprint or face sign-in is no longer on for this device.", { code: "biometric_unknown" }));
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  expect(screen.queryByLabelText("Password")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Use your password instead" }));
  expect(screen.getByLabelText("Password")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Use fingerprint or face instead" }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sign in as larry with fingerprint or face" })); });
  expect(api).toHaveBeenCalledWith("/api/v1/auth/biometric/sign-in/start/", expect.objectContaining({ body: JSON.stringify({ credential_id: "key-5" }) }));
  expect(screen.getByLabelText("Password")).toBeTruthy();
  expect(localStorage.getItem("lintech-biometric")).toBe("{}");
  delete window.PublicKeyCredential;
});

it("opens the fingerprint or face prompt as the page opens when one person has it on here", async () => {
  const { rememberKey } = await import("../../core/auth/biometric");
  localStorage.clear();
  rememberKey(5, "key-5", "larry");
  window.PublicKeyCredential = { isUserVerifyingPlatformAuthenticatorAvailable: async () => true };
  api.mockReset();
  api.mockRejectedValue(new ApiError(400, "Fingerprint or face not accepted.", { code: "wrong_biometric" }));
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  await act(async () => { await new Promise((done) => setTimeout(done, 10)); });
  expect(api).toHaveBeenCalledWith("/api/v1/auth/biometric/sign-in/start/", expect.anything());
  expect(api).toHaveBeenCalledTimes(1);
  delete window.PublicKeyCredential;
  localStorage.clear();
});

it("after a password sign-in on a device with a fingerprint, offers to turn it on with that password", async () => {
  const alerts = await import("../../core/ui/alerts");
  const offer = vi.spyOn(alerts, "confirmAction").mockResolvedValue(false);
  localStorage.clear();
  window.PublicKeyCredential = { isUserVerifyingPlatformAuthenticatorAvailable: async () => true };
  api.mockReset();
  api.mockResolvedValue({ authenticated: true, id: 9, username: "larry", organization: { id: 1 } });
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Username or email"), { target: { value: "larry" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Right-pass-1" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sign in" })); });
  expect(offer).toHaveBeenCalledWith(expect.objectContaining({ title: "Use fingerprint or face next time?" }));
  // Declined: nothing more is asked of the server than the sign-in itself.
  expect(api).toHaveBeenCalledTimes(1);
  delete window.PublicKeyCredential;
  offer.mockRestore();
});
