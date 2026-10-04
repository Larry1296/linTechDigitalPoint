import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ThemePicker } from "./components/ThemePicker";
import { AppNavbar } from "./components/AppChrome";
import { AuthProvider } from "./core/auth/AuthContext";
import { LoginPage } from "./modules/auth/AuthPages";
beforeAll(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input) => ({
      status: 200,
      ok: true,
      json: async () =>
        String(input).includes("/cart/")
          ? { id: 1, items: [], total: "0" }
          : {
              authenticated: false,
              is_staff: false,
              is_superuser: false,
              roles: [],
              permissions: [],
            },
    })),
  ),
);
describe("authentication experience", () => {
  it("defaults theme selector to System", () => {
    render(<ThemePicker />);
    expect(screen.getByRole("combobox")).toHaveValue("system");
  });
  it("does not offer customer registration", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "Welcome back" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create account" })).not.toBeInTheDocument();
  });
  it("shows no business navigation before login", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <AppNavbar />
        </AuthProvider>
      </MemoryRouter>,
    );
    const navigation = screen.getByRole("navigation", {
      name: "Main navigation",
    });
    expect(
      screen.getByRole("link", { name: "Login" }),
    ).toHaveAttribute("href", "/login");
    expect(
      within(navigation).queryByText("Owner Login"),
    ).not.toBeInTheDocument();
    expect(
      within(navigation).queryByText("Storefront"),
    ).not.toBeInTheDocument();
    expect(within(navigation).queryByText("Dashboard")).not.toBeInTheDocument();
    expect(within(navigation).queryByText("Point of Sale")).not.toBeInTheDocument();
    expect(within(navigation).getByText("Features")).toHaveAttribute("href", "/#features");
  });
});
