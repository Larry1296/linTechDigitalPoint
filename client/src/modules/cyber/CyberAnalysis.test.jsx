import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CyberAnalysis } from "./CyberAnalysis";
import { getCyberAnalysis } from "./api";
vi.mock("./api", () => ({ getCyberAnalysis: vi.fn() }));

it("shows income, services, busiest hours and waiting times", async () => {
  getCyberAnalysis.mockResolvedValue({
    days: [{ date: "2026-10-08", income: "300", jobs: 3, profit: "200" }, { date: "2026-10-09", income: "550", jobs: 2, profit: null }],
    services: [{ name: "Printing", income: "400", units: "40" }, { name: "Typing", income: "450", units: "9" }],
    hours: [{ hour: 9, count: 1 }, { hour: 10, count: 4 }], waits: [{ label: "Under 15 minutes", count: 5 }, { label: "Longer", count: 0 }],
  });
  render(<CyberAnalysis refreshKey={1} />);
  expect(await screen.findByText(/5 services done for KSh 850, about KSh 170 each/)).toBeInTheDocument();
  for (const title of ["Income each day", "Services done each day", "Services that bring the most", "Busiest hours", "How long customers wait"]) {
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  }
  expect(screen.getAllByRole("listitem").find((li) => /Typing/.test(li.textContent))).toHaveTextContent("9 units");
  expect(screen.getByText(/Most services are finished between 10/)).toBeInTheDocument();
});
