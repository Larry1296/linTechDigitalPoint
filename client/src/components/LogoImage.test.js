import { expect, it } from "vitest";
import { logoWidth } from "./LogoImage";

it("gives every logo the same visual weight: wide wordmarks get width, square marks get height", () => {
  const header = (aspect) => ({ width: logoWidth(aspect, "header"), height: logoWidth(aspect, "header") / aspect });
  expect(header(1)).toEqual({ width: 76, height: 76 });            // square icon: tallest allowed
  expect(header(3.4).height).toBeGreaterThan(55);                   // icon + word: letters stay large
  expect(header(8)).toEqual({ width: 280, height: 35 });            // long wordmark: as wide as the slot allows
  expect(logoWidth(20, "header")).toBe(280);                        // extreme banners stop at the slot width
});

it("grows header logos on large monitors and shrinks them on small screens", async () => {
  const { screenScale } = await import("./LogoImage");
  expect(screenScale(1366)).toBe(1);
  expect(screenScale(2560)).toBe(1.6);
  expect(screenScale(360)).toBe(0.85);
  expect(logoWidth(3.4, "header", 1.4)).toBeGreaterThan(logoWidth(3.4, "header", 1));
  expect(logoWidth(1, "header", 1.6)).toBeLessThanOrEqual(88);          // never taller than the header content
});
