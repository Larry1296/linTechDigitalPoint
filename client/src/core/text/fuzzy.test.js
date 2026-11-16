import { expect, it } from "vitest";
import { fuzzyScore } from "./fuzzy";

it("finds items whatever small slips the typed name has", () => {
  const cover = ["TECNO SPARK 40 HARD COVER (MEN)", "HARD (MEN)", "TEC-SP40-HARD-M"];
  expect(fuzzyScore("tecmo sprak", ...cover)).toBeGreaterThan(0.8);
  expect(fuzzyScore("tecn", ...cover)).toBe(1);
  expect(fuzzyScore("spark40", ...cover)).toBe(1);
  expect(fuzzyScore("infinix", ...cover)).toBeNull();
  expect(fuzzyScore("", ...cover)).toBe(1);
});
