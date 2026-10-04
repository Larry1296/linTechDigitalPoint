import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../core/api/client", async (original) => ({ ...(await original()), api: vi.fn() }));
vi.mock("../modules/assistant/BusinessAssistant", () => ({ BusinessAssistant: () => null }));
vi.mock("../modules/billing/SubscriptionBanner", () => ({ SubscriptionBanner: () => null }));
const auth = vi.hoisted(() => ({ modules: [] }));
vi.mock("../core/auth/AuthContext", () => ({ useAuth: () => ({ lock: vi.fn(), logout: vi.fn(), user: {
  username: "owner", roles: ["OWNER"], memberships: [{ organization: { id: 1, name: "LinTech" } }], branches: [],
  permissions: ["commerce.add_sale", "commerce.view_sale", "catalog.view_product", "cyber.view_cyberjob", "mpesa.view_mpesasession", "mpesa.view_mpesacommissionentry", "accounting.view_profit"],
  organization: { id: 1, name: "LinTech", enabled_modules: auth.modules, subscription: {} } } }) }));
import { api } from "../core/api/client";
import { StaffLayout } from "./StaffLayout";

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path) => (path === "/api/v1/cyber/services/"
    ? [{ id: 4, name: "Printing", active: true }, { id: 5, name: "Typing", active: true }, { id: 6, name: "Lamination", active: false }] : []));
});

const renderAt = async (path) => {
  await act(async () => { render(<MemoryRouter initialEntries={[path]}><StaffLayout /></MemoryRouter>); });
  return screen.getByRole("complementary");
};

it("groups the menu by business and opens only the group of the page shown; services open as full pages, not menu items", async () => {
  auth.modules = ["pos", "inventory", "services", "mpesa", "reports"];
  const sidebar = await renderAt("/admin/cyber/income/4");
  const cyber = within(sidebar).getByRole("button", { name: "Cyber Services" });
  const shop = within(sidebar).getByRole("button", { name: "Shop Management" });
  const agent = within(sidebar).getByRole("button", { name: "M-Pesa Agent" });
  expect(cyber).toHaveAttribute("aria-expanded", "true");
  expect(shop).toHaveAttribute("aria-expanded", "false");
  expect(within(sidebar).getByRole("link", { name: "Income by service" })).toHaveClass("active");
  expect(within(sidebar).queryByRole("link", { name: "Printing" })).toBeNull();
  expect(within(sidebar).queryByRole("link", { name: "Point of Sale" })).toBeNull();
  fireEvent.click(shop);
  expect(within(sidebar).getByRole("link", { name: "Point of Sale" })).toBeVisible();
  fireEvent.click(agent);
  expect(within(sidebar).getByRole("link", { name: "Agent desk" })).toHaveAttribute("href", "/admin/mpesa");
});

it("shows only the businesses that are switched on", async () => {
  auth.modules = ["pos", "inventory"];
  const sidebar = await renderAt("/admin/pos");
  expect(within(sidebar).getByRole("button", { name: "Shop Management" })).toHaveAttribute("aria-expanded", "true");
  expect(within(sidebar).queryByRole("button", { name: "Cyber Services" })).toBeNull();
  expect(within(sidebar).queryByRole("button", { name: "M-Pesa Agent" })).toBeNull();
});

it("highlights only the M-Pesa page shown, not the Agent desk as well", async () => {
  auth.modules = ["mpesa"];
  const sidebar = await renderAt("/admin/mpesa/commission");
  expect(within(sidebar).getByRole("link", { name: "Commission" })).toHaveClass("active");
  expect(within(sidebar).getByRole("link", { name: "Agent desk" })).not.toHaveClass("active");
});
