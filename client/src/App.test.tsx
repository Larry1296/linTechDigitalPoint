import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ThemePicker } from "./components/ThemePicker";
import { AppNavbar } from "./components/AppChrome";
import { AuthProvider } from "./core/auth/AuthContext";
import { CartProvider } from "./core/cart/CartContext";
import { LoginPage } from "./modules/auth/AuthPages";
beforeAll(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => ({
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
  it("preserves checkout intent in registration link", () => {
    render(
      <MemoryRouter initialEntries={["/login?next=/checkout"]}>
        <AuthProvider>
          <CartProvider>
            <LoginPage />
          </CartProvider>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "Welcome back" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Create account" }),
    ).toHaveAttribute("href", "/register?next=%2Fcheckout");
  });

  it("shows only customer-facing navigation before login", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <CartProvider>
            <AppNavbar />
          </CartProvider>
        </AuthProvider>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole("navigation", {
      name: "Main navigation",
    });
    expect(within(navigation).getByRole("link", { name: "Login/Register" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(within(navigation).queryByText("Owner Login")).not.toBeInTheDocument();
    expect(within(navigation).queryByText("Storefront")).not.toBeInTheDocument();
    expect(within(navigation).queryByText("Dashboard")).not.toBeInTheDocument();
    expect(within(navigation).queryByText("POS")).not.toBeInTheDocument();
  });
});
