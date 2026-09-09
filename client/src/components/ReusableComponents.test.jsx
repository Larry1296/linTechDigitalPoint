import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { PasswordField } from "./forms/PasswordField";
import { ProductCard } from "../modules/storefront/components/ProductCard";
import { SidebarNavigation } from "./navigation/SidebarNavigation";
import { Home } from "lucide-react";

const product = {
  id: 7,
  product_name: "Phone Cover",
  display_name: "Phone Cover — Blue",
  variant_count: 1,
  name: "Blue",
  category: "Covers",
  selling_price: "350.00",
  available: "2",
  online_orderable: true,
  images: [],
};

describe("shared storefront and form components", () => {
  it("toggles passwords independently without submitting or losing values", () => {
    const submit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={submit}>
        <PasswordField name="password" defaultValue="secret" />
        <PasswordField label="Confirm password" name="confirm_password" />
      </form>,
    );
    const password = screen.getByLabelText("Password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("secret");
    expect(screen.getByLabelText("Confirm password")).toHaveAttribute(
      "type",
      "password",
    );
    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
    expect(submit).not.toHaveBeenCalled();
  });
  it("renders featured products with a detail link and image fallback", () => {
    render(
      <MemoryRouter>
        <ProductCard product={product} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(
      "Phone Cover",
    );
    expect(screen.getByText("P")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View product" })).toHaveAttribute(
      "href",
      "/products/7",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("passes the selected product to the shared cart action", () => {
    const add = vi.fn();
    render(
      <MemoryRouter>
        <ProductCard product={product} onAdd={add} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Only 2 left")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    expect(add).toHaveBeenCalledWith(product);
  });
  it.each([
    ["0", true, true],
    [null, true, false],
    ["5", false, true],
  ])(
    "preserves ordering rules for availability %s and orderable %s",
    (available, online_orderable, disabled) => {
      render(
        <MemoryRouter>
          <ProductCard
            product={{ ...product, available, online_orderable }}
            onAdd={vi.fn()}
          />
        </MemoryRouter>,
      );
      expect(screen.getByRole("button").disabled).toBe(disabled);
    },
  );
  it("omits empty navigation groups and closes on navigation", () => {
    const close = vi.fn();
    render(
      <MemoryRouter>
        <SidebarNavigation
          label="Account"
          onNavigate={close}
          sections={[
            { title: "Hidden", links: [] },
            {
              title: "Shopping",
              links: [{ to: "/shop", label: "Shop", icon: Home }],
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText("HIDDEN")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Shop" }));
    expect(close).toHaveBeenCalledOnce();
  });
});
