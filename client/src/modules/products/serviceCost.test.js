import { expect, it } from "vitest";
import { serviceCostWarning } from "./serviceCost";

it("warns about a service cost with no price, or as much as the price, and is quiet otherwise", () => {
  expect(serviceCostWarning("0", "10")).toMatch(/wrong way round/);
  expect(serviceCostWarning("10", "10")).toMatch(/the same as the price/);
  expect(serviceCostWarning("5", "10")).toMatch(/more than the price/);
  expect(serviceCostWarning("1500", "200")).toBe("");
  expect(serviceCostWarning("20", "0")).toBe("");
  expect(serviceCostWarning("", "")).toBe("");
});
