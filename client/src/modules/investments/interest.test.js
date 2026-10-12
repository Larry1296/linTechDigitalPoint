import { expect, it } from "vitest";
import { earnings, projectInterest } from "./interest";

it("works out a month's interest after withholding tax and adds it to the balance", () => {
  const result = projectInterest({ amount: 100000, annualRate: 12, months: 1, taxRate: 15 });
  expect(result.rows).toEqual([{ month: 1, added: 0, interest: 850, tax: 150, balance: 100850 }]);
  expect(result).toMatchObject({ putIn: 100000, gross: 1000, tax: 150, net: 850, balance: 100850 });
});

it("earns interest on last month's interest and on monthly top-ups", () => {
  const result = projectInterest({ amount: 100000, annualRate: 12, months: 3, topUp: 10000, taxRate: 15 });
  expect(result.putIn).toBe(120000);
  expect(result.rows[1]).toEqual({ month: 2, added: 10000, interest: 942.23, tax: 166.28, balance: 111792.23 });
  expect(result.balance).toBe(result.putIn + result.net);
});

it("handles empty or silly input without breaking", () => {
  expect(projectInterest({ amount: "", annualRate: "", months: "" })).toMatchObject({ rows: [], balance: 0, net: 0 });
  expect(projectInterest({ amount: 1000, annualRate: 10, months: 5000 }).rows).toHaveLength(600);
});

it("says what a balance earns a day, a month and a year after tax", () => {
  // The year counts each month's interest earning interest after it is added: more than 12 × the month.
  expect(earnings(365000, 10, 15)).toEqual({ day: 85, month: 2585.42, year: 32262.68 });
  expect(earnings(365000, 10, 0).day).toBe(100);
});
