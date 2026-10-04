import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
vi.mock("../../core/api/client", () => ({ api: vi.fn() }));
import { api } from "../../core/api/client";
import { DeleteProductsDialog } from "./DeleteProducts";

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation(async (path) => (path.endsWith("delete-check/") ? [
    { id: 1, name: "C-C HEAD(45W)", active: true, can_remove: false, reason: "it has been sold", on_shelf: "1" },
    { id: 2, name: "MORIMAXE", active: true, can_remove: true, reason: "", on_shelf: "3" },
  ] : [{ id: 1, name: "C-C HEAD(45W)", result: "hidden" }, { id: 2, name: "MORIMAXE", result: "removed" }]));
});

it("asks whether to keep the records or remove permanently, and explains what each product allows", async () => {
  const done = vi.fn();
  render(<DeleteProductsDialog ids={[1, 2]} canHide canRemove onClose={vi.fn()} onDone={done} />);
  expect(await screen.findByText(/Its records must be kept: it has been sold/)).toBeInTheDocument();
  expect(screen.getByText(/can be removed permanently/)).toBeInTheDocument();
  expect(screen.getByLabelText(/Delete, but keep the records/)).toBeChecked();
  fireEvent.click(screen.getByLabelText(/Remove permanently/));
  expect(screen.getByText(/1 will be erased completely; the other 1 can only be deleted with their records kept/)).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Remove permanently" });
  expect(button).toBeDisabled();  // until the owner confirms it cannot be undone
  fireEvent.click(screen.getByLabelText("I understand this cannot be undone."));
  fireEvent.click(button);
  await waitFor(() => expect(done).toHaveBeenCalled());
  const body = JSON.parse(api.mock.calls.find(([p]) => p.endsWith("bulk-delete/"))[1].body);
  expect(body).toEqual({ ids: [1, 2], mode: "remove", hide_rest: true });
});

it("offers only keeping the records when nothing selected can be removed", async () => {
  api.mockImplementation(async () => [{ id: 1, name: "C-C HEAD(45W)", active: true, can_remove: false, reason: "it has been sold", on_shelf: "0" }]);
  render(<DeleteProductsDialog ids={[1]} canHide canRemove onClose={vi.fn()} onDone={vi.fn()} />);
  expect(await screen.findByLabelText(/Remove permanently/)).toBeDisabled();
  expect(screen.getByText(/KRA requires records for 5 years/)).toBeInTheDocument();
});
