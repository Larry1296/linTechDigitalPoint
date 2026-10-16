import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
import { api } from "../../core/api/client";
import { SalesProfits } from "./SalesProfits";

const money = (value) => value == null ? "Restricted" : `KSh ${Number(value).toLocaleString()}`;
const sale = (id, number, figures) => ({ id, number, created_at: "2026-10-16T09:00:00Z", customer: "Walk-in", items: [{ id, item: "Phone cover", quantity: "2" }], figures });

it("lists every sale with what it cost and the profit it made, page by page", async () => {
  api.mockImplementation(async (path) => path.includes("page=2")
    ? { count: 51, profit_visible: true, results: [sale(3, "S-3", { sales: "100", cost: "120", profit: "-20" })] }
    : { count: 51, profit_visible: true, results: [sale(1, "S-1", { sales: "400", cost: "190", profit: "210" }), sale(2, "S-2", { sales: "200", cost: "100", profit: "100" })] });
  render(<SalesProfits money={money} timezone="Africa/Nairobi" refreshKey="0" />);
  expect(await screen.findByRole("row", { name: /S-1 Walk-in 2 × Phone cover KSh 400 KSh 190 KSh 210 profit/ })).toBeInTheDocument();
  expect(screen.getByRole("row", { name: /These 2 sales KSh 600 KSh 290 KSh 310 profit/ })).toBeInTheDocument();
  expect(screen.getByText(/51 sales in all · page 1 of 2/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Older sales" }));
  expect(await screen.findByRole("row", { name: /S-3 .* KSh 20 loss/ })).toBeInTheDocument();
});

it("stays hidden from someone who may not see profit", async () => {
  api.mockResolvedValue({ count: 1, profit_visible: false, results: [sale(1, "S-1")] });
  const { container } = render(<SalesProfits money={money} timezone="Africa/Nairobi" refreshKey="0" />);
  await waitFor(() => expect(api).toHaveBeenCalled());
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});
