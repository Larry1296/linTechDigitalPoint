import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter, Link, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BackLink, canGoBack } from "./BackLink";
function Pages() {
  const location = useLocation();
  return <><output data-testid="location">{location.pathname}{location.search}{location.hash}</output><BackLink /><Link to="/login">Sign in</Link><Link to="/forgot-password">Reset password</Link><Link to="/admin/products">Products</Link></>;
}
beforeEach(() => window.history.replaceState({ idx: 0 }, "", "/pricing?plan=annual#plans"));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it("returns through authentication pages to the exact originating URL", async () => {
  render(<BrowserRouter><Pages /></BrowserRouter>);
  fireEvent.click(screen.getByText("Sign in"));
  fireEvent.click(screen.getByText("Reset password"));
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/login"));
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/pricing?plan=annual#plans"));
});
it("returns from products to its caller after remounting", async () => {
  window.history.replaceState({ idx: 0 }, "", "/admin/receive?receipt=42#items");
  const view = render(<BrowserRouter><Pages /></BrowserRouter>);
  fireEvent.click(screen.getByText("Products"));
  view.unmount();
  render(<BrowserRouter><Pages /></BrowserRouter>);
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/admin/receive?receipt=42#items"));
});
it.each([["/admin/products", "/admin/dashboard"], ["/reset-password", "/"]])("uses a safe fallback for direct visits to %s", (path, expected) => {
  window.history.replaceState({ idx: 0 }, "", path);
  render(<BrowserRouter><Pages /></BrowserRouter>);
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  expect(screen.getByTestId("location").textContent).toBe(expected);
});
it("recognizes same-origin document links but not external referrers", () => {
  vi.spyOn(window.history, "length", "get").mockReturnValue(2);
  vi.spyOn(document, "referrer", "get").mockReturnValue(`${window.location.origin}/admin/receipts?status=posted`);
  expect(canGoBack()).toBe(true);
  vi.spyOn(document, "referrer", "get").mockReturnValue("https://external.example/");
  expect(canGoBack()).toBe(false);
});
it("goes straight to its target when given one, ignoring history", async () => {
  window.history.replaceState({ idx: 0 }, "", "/admin/dashboard");
  function Auth() {
    const location = useLocation();
    return <><output data-testid="location">{location.pathname}</output><Link to="/login">Sign in</Link><BackLink to="/" /></>;
  }
  render(<BrowserRouter><Auth /></BrowserRouter>);
  fireEvent.click(screen.getByText("Sign in"));
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/"));
});
