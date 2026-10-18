import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { username: "amina", roles: [] } }) }));
vi.mock("../core/auth/useSignOut", () => ({ useSignOut: () => vi.fn() }));
vi.mock("../modules/platform/PlatformContext", () => ({ usePlatform: () => ({ name: "LinTech" }) }));
import { CustomerLayout } from "./CustomerLayout";

afterEach(() => { delete window.matchMedia; });

it("on a phone, the navbar's one hamburger opens and closes the customer account menu", async () => {
  window.matchMedia = (query) => ({ matches: query === "(max-width: 760px)" || query === "(max-width: 1250px)", addEventListener() {}, removeEventListener() {} });
  await act(async () => { render(<MemoryRouter initialEntries={["/account"]}><CustomerLayout /></MemoryRouter>); });
  expect(screen.queryByRole("link", { name: /get started/i })).toBeNull();
  const toggle = screen.getByRole("button", { name: "Open account menu" });
  expect(document.getElementById("customer-sidebar")).not.toHaveClass("isOpen");
  fireEvent.click(toggle);
  expect(document.getElementById("customer-sidebar")).toHaveClass("isOpen");
  fireEvent.click(screen.getByRole("button", { name: "Close account menu", expanded: true }));
  expect(document.getElementById("customer-sidebar")).not.toHaveClass("isOpen");
});
