import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter, Link, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BackLink, canGoBack, parentPage } from "./BackLink";
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
it("in the workspace goes one level up, never back to whichever page was open before", async () => {
  window.history.replaceState({ idx: 0 }, "", "/admin/receive?receipt=42#items");
  render(<BrowserRouter><Pages /></BrowserRouter>);
  fireEvent.click(screen.getByText("Products"));
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/admin/dashboard"));
  expect(screen.queryByRole("button", { name: "← Back" })).toBeNull();  // the dashboard is the top
});
it.each([
  ["/admin/cyber/income/733", "/admin/cyber/income"], ["/admin/cyber/income", "/admin/cyber"], ["/admin/cyber", "/admin/dashboard"],
  ["/admin/mpesa/commission", "/admin/mpesa"], ["/admin/rooms/stays/5", "/admin/rooms"], ["/admin/chama/3/", "/admin/chama"],
  ["/admin/receipts/9", "/admin/receipts"], ["/admin/reports/journals", "/admin/reports"], ["/admin/expenses", "/admin/dashboard"],
  ["/admin/dashboard", null], ["/admin", null], ["/pricing", null],
])("the page above %s is %s", (path, expected) => expect(parentPage(path)).toBe(expected));
it("uses a safe fallback for direct visits outside the workspace", () => {
  window.history.replaceState({ idx: 0 }, "", "/reset-password");
  render(<BrowserRouter><Pages /></BrowserRouter>);
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  expect(screen.getByTestId("location").textContent).toBe("/");
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
