import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
import { api } from "../../core/api/client";
import { OneDrawerShare } from "./OneDrawerShare";

const shares = { total: "31500.00", parts: [
  { key: "SHOP", label: "Shop", amount: "1000.00", sales: "1500.00", cogs: "500.00", expenses: "0", profit: "1000.00" },
  { key: "CYBER", label: "Cyber", amount: "500.00", sales: "500.00", cogs: "0", expenses: "0", profit: "500.00" },
  { key: "MPESA", label: "M-Pesa", amount: "30000.00", sales: "0", cogs: "0", expenses: "0", profit: "0" }] };

it("on the M-Pesa desk lists every part's share of all the money held", async () => {
  api.mockResolvedValue({ shares });
  render(<OneDrawerShare />);
  expect(await screen.findByRole("heading", { name: /Money in operation: KSh 31,500/ })).toBeInTheDocument();
  expect(screen.getByText("Cyber").nextSibling).toHaveTextContent("KSh 500");
  expect(screen.getByText("Shop").nextSibling).toHaveTextContent("KSh 1,000");
});

it("on the shop's page shows its own share, what it sold and what the items cost", async () => {
  api.mockResolvedValue({ shares });
  render(<OneDrawerShare part="SHOP" />);
  expect((await screen.findByText(/Shop.s share of the money the business holds: KSh 1,000/)).closest("p")).toHaveTextContent("of KSh 31,500");
  expect(screen.getByText(/Since the start/)).toHaveTextContent("sold KSh 1,500, items cost KSh 500 (buying price); profit KSh 1,000");
});

it("shows nothing when the parts keep their money apart", async () => {
  api.mockResolvedValue({ shares: null });
  const { container } = render(<OneDrawerShare part="SHOP" />);
  await Promise.resolve();
  expect(container).toBeEmptyDOMElement();
});
