import { afterEach, expect, it } from "vitest";
import { businessNow, businessToday, setBusinessPresentation } from "./presentation";

afterEach(() => setBusinessPresentation(null));

it("gives today's date and the time now where the business is, not in UTC", () => {
  setBusinessPresentation({ timezone: "Africa/Nairobi" });
  // 21:30 UTC on 19 October is already 00:30 on 20 October in Nairobi.
  const lateEvening = new Date("2026-10-19T21:30:00Z");
  expect(businessToday(lateEvening)).toBe("2026-10-20");
  expect(businessNow(lateEvening)).toBe("2026-10-20T00:30");
});
