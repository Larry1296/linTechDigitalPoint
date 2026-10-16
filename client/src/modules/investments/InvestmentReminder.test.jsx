import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
let permissions = [];
let modules = ["investments"];
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions, organization: { enabled_modules: modules } } }) }));
import { api } from "../../core/api/client";
import { InvestmentReminder } from "./InvestmentReminder";

beforeEach(() => { vi.clearAllMocks(); permissions = ["accounting.view_investment"]; modules = ["investments"]; });

it("reminds the owner on the dashboard when this month's check is due", async () => {
  api.mockResolvedValue({ month: "October 2026", due: [{ id: 3, name: "CIC MMF" }] });
  render(<InvestmentReminder />);
  expect(await screen.findByRole("status", { name: "Investment check due" })).toHaveTextContent("Record the rate CIC MMF pays now");
  expect(screen.getByRole("link", { name: "Go to investments" })).toHaveAttribute("href", "/admin/investments");
});

it("says nothing when every check is done or the person cannot see investments", async () => {
  api.mockResolvedValue({ month: "October 2026", due: [] });
  const { container } = render(<InvestmentReminder />);
  await vi.waitFor(() => expect(api).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
  permissions = [];
  vi.clearAllMocks();
  render(<InvestmentReminder />);
  expect(api).not.toHaveBeenCalled();
  // A business that does not keep investments is not asked about them either.
  permissions = ["accounting.view_investment"];
  modules = ["pos"];
  render(<InvestmentReminder />);
  expect(api).not.toHaveBeenCalled();
});
