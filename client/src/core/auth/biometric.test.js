import { afterEach, expect, it } from "vitest";
import { forgetKey, keyHere, rememberKey } from "./biometric";

afterEach(() => localStorage.clear());

it("remembers which person turned on fingerprint or face unlock in this browser", () => {
  expect(keyHere(7)).toBeNull();
  rememberKey(7, "abc");
  expect(keyHere(7)).toBe("abc");
  expect(keyHere(8)).toBeNull();
  forgetKey(7);
  expect(keyHere(7)).toBeNull();
});
