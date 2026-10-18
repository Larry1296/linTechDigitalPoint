import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("./PlatformContext", () => ({ usePlatform: () => ({ name: "LinTech" }) }));
import { PublicNavbar } from "./PublicSite";

afterEach(() => { delete window.matchMedia; document.body.style.overflow = ""; });

it("on a small screen the hamburger opens a full-screen menu with every link and button, and Escape closes it", () => {
  window.matchMedia = (query) => ({ matches: query === "(max-width: 1250px)", addEventListener() {}, removeEventListener() {} });
  render(<MemoryRouter><PublicNavbar /></MemoryRouter>);
  expect(screen.queryByRole("link", { name: /get started/i })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
  const menu = screen.getByRole("dialog", { name: "Menu" });
  expect(menu.parentElement).toBe(document.body);
  expect(document.body.style.overflow).toBe("hidden");
  for (const name of ["Features", "Business management", "Pricing", "Contact", /get started/i, /login/i]) {
    expect(within(menu).getByRole("link", { name })).toBeVisible();
  }
  expect(within(menu).getByRole("combobox", { name: "Theme" })).toBeVisible();
  expect(within(menu).getByRole("link", { name: "Features" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.body.style.overflow).toBe("");
});

it("on a wide screen the links and buttons stay in the bar", () => {
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  render(<MemoryRouter><PublicNavbar /></MemoryRouter>);
  expect(screen.getByRole("link", { name: "Features" })).toBeVisible();
  expect(screen.getByRole("link", { name: /get started/i })).toBeVisible();
});
