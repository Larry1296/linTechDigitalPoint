import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CategoryOptions, UnrackedHint, categoryFamily, rackHolds } from "./categories";

const categories = [
  { id: 3, name: "Electrical", available: false, rack_ids: [], descendant_ids: [3] },
  { id: 1, name: "Mobile Accessories", available: true, rack_ids: [7], descendant_ids: [1, 2] },
  { id: 2, name: "Wall Chargers – Mobile Accessories", available: true, rack_ids: [7], descendant_ids: [2] },
];

it("lists every category child first and greys out those not on a rack", () => {
  render(<><select aria-label="Category"><CategoryOptions categories={categories} /></select><UnrackedHint categories={categories} /></>);
  expect(screen.getByRole("option", { name: "Wall Chargers – Mobile Accessories" })).toBeEnabled();
  expect(screen.getByRole("option", { name: "Electrical (not on a rack yet)" })).toBeDisabled();
  expect(screen.getByText(/Greyed-out categories aren't on a rack yet/)).toBeInTheDocument();
});

it("a parent includes its sub-categories and a sub-category uses its parent's rack", () => {
  expect(categoryFamily(categories, "1")).toEqual([1, 2]);
  expect(rackHolds({ id: 7, categories: [{ id: 1 }] }, categories, "2")).toBe(true);
  expect(rackHolds({ id: 8, categories: [] }, categories, "2")).toBe(false);
});
