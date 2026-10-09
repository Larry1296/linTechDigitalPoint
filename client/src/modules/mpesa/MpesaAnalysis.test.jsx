import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MpesaAnalysis } from "./MpesaAnalysis";
import { getMpesaAnalysis } from "./api";
vi.mock("./api", () => ({ getMpesaAnalysis: vi.fn() }));

const data = {
  working_days: 2, unknown: 1,
  days: [{ date: "2026-10-09", deposits: "5000", withdrawals: "3000", airtime: "200", count: 6, commission: "60" },
    { date: "2026-10-10", deposits: "7000", withdrawals: "4000", airtime: "0", count: 9, commission: "95" }],
  hours: [{ hour: 8, count: 3 }, { hour: 9, count: 8 }, { hour: 10, count: 4 }],
  sizes: [{ label: "Up to 100", count: 2 }, { label: "101 to 500", count: 5 }, { label: "Over 10,000", count: 1 }],
  commission_by_kind: [{ kind: "deposits", amount: "40" }, { kind: "withdrawals", amount: "110" }, { kind: "airtime", amount: "5" }],
};
beforeEach(() => { vi.clearAllMocks(); getMpesaAnalysis.mockResolvedValue(data); });

it("shows the agency's days, hours, sizes and commission, and changes the period", async () => {
  render(<MpesaAnalysis refreshKey={1} />);
  expect(await screen.findByRole("heading", { name: "Money through the agency each day" })).toBeInTheDocument();
  for (const title of ["Commission earned each day", "Transactions each day", "Busiest hours", "Transaction sizes", "Which transactions earn the commission"]) {
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  }
  expect(screen.getByText(/15 transactions over 2 working days/)).toBeInTheDocument();
  expect(screen.getByText(/1 of them have commission not worked out yet/)).toBeInTheDocument();
  expect(screen.getByText(/Most transactions happen between 9/)).toBeInTheDocument();
  expect(screen.getAllByRole("listitem").at(-3)).toHaveTextContent(/^Withdrawals/);  // biggest earner first
  fireEvent.change(screen.getByRole("combobox", { name: "Period" }), { target: { value: "90" } });
  await waitFor(() => expect(getMpesaAnalysis).toHaveBeenLastCalledWith(90));
});

it("says so when nothing has happened yet", async () => {
  getMpesaAnalysis.mockResolvedValue({ ...data, days: data.days.map((d) => ({ ...d, count: 0 })) });
  render(<MpesaAnalysis refreshKey={1} />);
  expect(await screen.findByText(/No deposits, withdrawals or airtime in these days yet/)).toBeInTheDocument();
});
