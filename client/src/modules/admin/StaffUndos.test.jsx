import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
vi.mock("../../core/data/liveRefresh", () => ({ useLiveRefresh: () => {} }));
import { api } from "../../core/api/client";
import { StaffUndos } from "./StaffUndos";

it("shows the owner what staff undid, with who did it and the reason they gave", async () => {
  api.mockResolvedValue([{ id: 1, at: "2026-10-31T09:30:00Z", who: "Jane", what: "Cancelled an M-Pesa transaction",
    detail: "customer deposit QK12 of 500.00", reason: "Entered twice" }]);
  render(<StaffUndos />);
  expect(await screen.findByRole("heading", { name: "Undone or corrected by your staff" })).toBeInTheDocument();
  expect(screen.getByText("Jane")).toBeInTheDocument();
  expect(screen.getByText("Entered twice")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/api/v1/inventory/dashboard/staff-undos/");
});

it("shows nothing when staff undid nothing", async () => {
  api.mockResolvedValue([]);
  const { container } = render(<StaffUndos />);
  await Promise.resolve();
  expect(container).toBeEmptyDOMElement();
});
