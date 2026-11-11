import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Paged, Pager } from "./Pager";

const rows = Array.from({ length: 45 }, (_, i) => `Row ${i + 1}`);
const List = ({ items }) => <Paged rows={items} noun="rows">{(page) => <ul>{page.map((r) => <li key={r}>{r}</li>)}</ul>}</Paged>;

it("shows 10 at a time with where you are, and moves between pages", () => {
  render(<List items={rows} />);
  expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(rows.slice(0, 10));
  expect(screen.getByText("1–10 of 45 rows")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "‹ Previous" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next ›" }));
  expect(screen.getByText("11–20 of 45 rows")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Page 2" })).toHaveAttribute("aria-current", "page");
  fireEvent.click(screen.getByRole("button", { name: "Page 5" }));
  expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(rows.slice(40));
  expect(screen.getByRole("button", { name: "Next ›" })).toBeDisabled();
});

it("shows no pager while everything fits on one page", () => {
  render(<List items={rows.slice(0, 10)} />);
  expect(screen.queryByRole("navigation")).toBeNull();
});

it("falls back to the last page when rows on it are removed", () => {
  const { rerender } = render(<List items={rows} />);
  fireEvent.click(screen.getByRole("button", { name: "Page 5" }));
  act(() => rerender(<List items={rows.slice(0, 38)} />));
  expect(screen.getByText("31–38 of 38 rows")).toBeInTheDocument();
});

it("offers the first, last and nearby pages with gaps between", () => {
  render(<Pager page={6} pages={20} count={200} onPage={() => {}} noun="jobs" />);
  expect(screen.getAllByRole("button", { name: /^Page / }).map((b) => b.textContent)).toEqual(["1", "5", "6", "7", "20"]);
  expect(screen.getAllByText("…")).toHaveLength(2);
});
