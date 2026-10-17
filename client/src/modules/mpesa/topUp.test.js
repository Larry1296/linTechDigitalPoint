import { expect, it } from "vitest";
import { sourceChoices } from "./topUp";

const amount = (value) => `KSh ${Number(value).toLocaleString()}`;
const sources = [{ value: "SHOP:CASH", label: "Shop's money: cash in the drawer", available: "1000" }, { value: "CYBER:CASH", label: "Cyber's money: cash in the drawer", available: "250" }];

it("offers the agency's own drawer cash for float, each other part's money with what it has, and outside the business", () => {
  expect(sourceChoices(sources, amount, { withDrawer: true }).map(([value]) => value)).toEqual(["", "DRAWER", "SHOP:CASH", "CYBER:CASH", "OUTSIDE"]);
  expect(sourceChoices(sources, amount, { withDrawer: true })[2][1]).toBe("Shop's money: cash in the drawer (KSh 1,000 there now)");
});

it("leaves the agency's own drawer out when cash is brought into the drawer", () => {
  expect(sourceChoices(sources, amount, { withDrawer: false }).map(([value]) => value)).toEqual(["", "SHOP:CASH", "CYBER:CASH", "OUTSIDE"]);
});
