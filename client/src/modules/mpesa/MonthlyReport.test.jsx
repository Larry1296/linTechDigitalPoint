import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", () => ({ getMpesaReportMonths: vi.fn(), downloadMpesaReport: vi.fn() }));
import { downloadMpesaReport, getMpesaReportMonths } from "./api";
import { MonthlyReport } from "./MonthlyReport";

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:report");
  URL.revokeObjectURL = vi.fn();
});

it("offers the month that just ended, and earlier months on request", async () => {
  getMpesaReportMonths.mockResolvedValue([{ month: "2026-08", label: "August 2026", shifts: 24 }, { month: "2026-07", label: "July 2026", shifts: 26 }]);
  downloadMpesaReport.mockResolvedValue(new Blob(["%PDF"], { type: "application/pdf" }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<MonthlyReport />);
  fireEvent.click(await screen.findByRole("button", { name: "Download August 2026 report (PDF)" }));
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(downloadMpesaReport).toHaveBeenCalledWith("2026-08");
  fireEvent.change(screen.getByLabelText("Earlier month"), { target: { value: "2026-07" } });
  fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
  await waitFor(() => expect(downloadMpesaReport).toHaveBeenCalledWith("2026-07"));
});

it("shows nothing until a month has ended, or to staff who cannot see reports", async () => {
  getMpesaReportMonths.mockRejectedValue(new Error("Only an owner or manager can generate M-Pesa reports."));
  const { container } = render(<MonthlyReport />);
  await waitFor(() => expect(getMpesaReportMonths).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
