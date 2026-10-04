import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductImport, errorReport } from "./ProductImport";
import { api } from "../../core/api/client";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
afterEach(() => vi.resetAllMocks());

const summary = {
  rows: 2, create: 1, skip: 1, errors: 0, error_count: 0, file_errors: [], stock_items: 1, services: 0, with_opening_stock: 1,
  total_quantity: "10", opening_value: "1800.00", new_categories: ["Mobile Accessories > Cables"], new_brands: [],
  rack_issues: [], rack_choices: [], racks: [], previous_import: null, online: false,
};
const rows = [
  { row: 2, name: "Charger", sku: "CHG", variant_name: "Standard", product_type: "STOCK_ITEM", category: "Mobile Accessories > Cables",
    shelf: "AL1C1S1 (Rack, level 1)", action: "create", opening_quantity: "10", opening_unit_cost: "180", opening_value: "1800.00", errors: [], notes: [] },
  { row: 3, name: "Cable", sku: "CAB", action: "skip", category: "Mobile Accessories", shelf: "", opening_quantity: "0", opening_unit_cost: "0",
    opening_value: "0.00", errors: [], notes: ["Already imported in IMPORT-1 (row 2): skipped, nothing changes."] },
];

function choose() {
  const file = new File(["x"], "products.xlsx");
  fireEvent.change(screen.getByLabelText("Completed template (.xlsx)"), { target: { files: [file] } });
}

it("reviews the file first, then imports every row on confirmation", async () => {
  api.mockResolvedValueOnce({ rows, summary, committed: false })
    .mockResolvedValueOnce({ rows, summary, committed: true, reference: "IMPORT-2" });
  const imported = vi.fn();
  render(<ProductImport onClose={() => {}} onImported={imported} />);
  choose();
  fireEvent.click(screen.getByRole("button", { name: "Check file" }));
  await screen.findByText("Categories to create:");
  expect(api.mock.calls[0][1].body.get("commit")).toBe("false");
  expect(screen.getByText(/Already imported in IMPORT-1/)).toBeInTheDocument();
  expect(screen.getByText(/1 row was already in the system and will be skipped/)).toBeInTheDocument();
  expect(screen.queryByText(/ecommerce|online_orderable/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Import 1 product" }));
  await screen.findByText("Products imported");
  expect(api.mock.calls[1][1].body.get("commit")).toBe("true");
  expect(screen.getByText(/not visible or orderable online/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(imported).toHaveBeenCalledOnce();
});

it("shows errors by row and column, offers a report and no import", async () => {
  const bad = [rows[0], { ...rows[1], action: "create", notes: [], errors: [{ column: "opening_unit_cost", message: "is required for opening stock of 5: enter the buying cost of one unit." }] }];
  api.mockResolvedValueOnce({ rows: bad, summary: { ...summary, errors: 1, error_count: 1 }, committed: false });
  render(<ProductImport onClose={() => {}} onImported={() => {}} />);
  choose();
  fireEvent.click(screen.getByRole("button", { name: "Check file" }));
  await screen.findByText(/is required for opening stock of 5/);
  expect(screen.getByText("opening_unit_cost", { selector: "li strong" })).toBeInTheDocument();
  expect(screen.queryByText("Charger")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download error report" })).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument());
  expect(errorReport({ rows: bad, summary: { file_errors: [] } }).split("\r\n")).toEqual([
    '"row","column","sku","name","error"',
    '"3","opening_unit_cost","CAB","Cable","is required for opening stock of 5: enter the buying cost of one unit."',
  ]);
});

it("asks for a rack for unracked categories and sends only the chosen racks", async () => {
  const issue = { category: "Car Accessories", new: true, rows: [2], suggested_racks: [7] };
  const unracked = { ...summary, errors: 1, error_count: 1, rack_issues: [issue], racks: [{ id: 7, name: "Front Rack", area: "Zone A" }, { id: 8, name: "Back Rack", area: "Zone B" }] };
  api.mockResolvedValueOnce({ rows: [{ ...rows[0], errors: [{ column: "category", message: "'Car Accessories' is not on a rack yet." }] }], summary: unracked, committed: false })
    .mockResolvedValueOnce({ rows, summary: { ...summary, rack_choices: [{ category: "Car Accessories", rack_id: 8, rack: "Back Rack" }] }, committed: false });
  render(<ProductImport onClose={() => {}} onImported={() => {}} />);
  choose();
  fireEvent.click(screen.getByRole("button", { name: "Check file" }));
  const select = await screen.findByLabelText(/Car Accessories \(new\)/);
  expect(select.value).toBe("");  // never pre-selected
  expect(screen.getByRole("option", { name: "Front Rack (Zone A) — holds this file's shelf" })).toBeInTheDocument();
  fireEvent.change(select, { target: { value: "8" } });
  fireEvent.click(screen.getByRole("button", { name: "Check again" }));
  await screen.findByText("Car Accessories → Back Rack");
  expect(JSON.parse(api.mock.calls[1][1].body.get("rack_choices"))).toEqual({ "Car Accessories": "8" });
});

it("says there is nothing to import when every row was imported before", async () => {
  api.mockResolvedValueOnce({ rows: [rows[1]], summary: { ...summary, rows: 1, create: 0, skip: 1, new_categories: [],
    previous_import: { reference: "IMPORT-1", created_at: "2026-09-28T10:00:00Z", by: "owner" } }, committed: false });
  render(<ProductImport onClose={() => {}} onImported={() => {}} />);
  choose();
  fireEvent.click(screen.getByRole("button", { name: "Check file" }));
  await screen.findByText("Nothing new to import: every row in this file is already in the system.");
  expect(screen.getByText(/This exact file was imported before \(IMPORT-1/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();
});
