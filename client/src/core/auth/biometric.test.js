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

it("names the check each kind of device uses", async () => {
  const { deviceCheck } = await import("./biometric");
  const as = (ua, width = 390, height = 844, touch = 5) => {
    Object.defineProperty(navigator, "userAgent", { value: ua, configurable: true });
    Object.defineProperty(navigator, "maxTouchPoints", { value: touch, configurable: true });
    Object.defineProperty(window, "screen", { value: { width, height }, configurable: true });
    return deviceCheck().name;
  };
  expect(as("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")).toBe("Face ID");
  expect(as("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", 375, 667)).toBe("Touch ID");
  expect(as("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)", 1440, 900, 0)).toBe("Touch ID");
  expect(as("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", 1920, 1080, 0)).toBe("Windows Hello");
  expect(as("Mozilla/5.0 (Linux; Android 14; SM-A546E) Mobile")).toBe("fingerprint or face");
});
