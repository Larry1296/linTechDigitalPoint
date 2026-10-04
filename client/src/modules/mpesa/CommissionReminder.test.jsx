import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
let permissions = [];
vi.mock("../../core/auth/AuthContext", () => ({ useAuth: () => ({ user: { permissions } }) }));
import { api } from "../../core/api/client";
import { CommissionReminder } from "./CommissionReminder";

beforeEach(() => { vi.clearAllMocks(); permissions = ["mpesa.view_mpesacommissionentry"]; });

it("reminds on the dashboard when last month's commission is not recorded", async () => {
  api.mockResolvedValue({ due_label: "September 2026" });
  render(<CommissionReminder />);
  expect(await screen.findByRole("status", { name: "Commission due" })).toHaveTextContent("September 2026's Safaricom commission is not recorded");
  expect(screen.getByRole("link", { name: "Record commission" })).toHaveAttribute("href", "/admin/mpesa/commission");
});

it("stays quiet when it is recorded or the person cannot see commission", async () => {
  api.mockResolvedValue({ due_label: null });
  const { container } = render(<CommissionReminder />);
  await vi.waitFor(() => expect(api).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
  permissions = [];
  vi.clearAllMocks();
  render(<CommissionReminder />);
  expect(api).not.toHaveBeenCalled();
});
