import { expect, it } from "vitest";
import { code128Modules, ean13Modules, eanCheck, isEan13, matchesCode, sameCode } from "./codes";

it("checks and draws EAN-13, the shop's own codes included", () => {
  expect(eanCheck("400638133393")).toBe("1");
  expect(isEan13("4006381333931")).toBe(true);
  expect(isEan13("4006381333932")).toBe(false);
  const bits = ean13Modules("4006381333931");
  expect(bits).toHaveLength(95);
  expect(bits.slice(0, 3)).toBe("101");
  expect(bits.slice(45, 50)).toBe("01010");
});

it("draws Code 128 for other codes: start, one symbol a character, check, stop", () => {
  expect(code128Modules("AB")).toHaveLength(11 * 4 + 13);
});

it("matches what the camera read to the product, with or without UPC's leading zero", () => {
  expect(sameCode("0012345678905", "012345678905")).toBe(true);
  expect(sameCode("ABC-1", "abc-1")).toBe(true);
  expect(sameCode("123", "")).toBe(false);
  expect(matchesCode({ sku: "ITL-A16", barcode: null }, "itl-a16")).toBe(true);
});
