import { act, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { businessDate, useNewBusinessDay } from "./businessDay";

afterEach(() => vi.useRealTimers());

function Watcher({ onNewDay }) {
  useNewBusinessDay(onNewDay);
  return null;
}

it("reads dates in the business's time zone (Nairobi by default)", () => {
  expect(businessDate("2026-09-26T20:59:00Z")).toBe("2026-09-26"); // 23:59 in Nairobi
  expect(businessDate("2026-09-26T21:00:00Z")).toBe("2026-09-27"); // 00:00 in Nairobi
});

it("fires once just after midnight, not before", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-26T20:58:00Z")); // 23:58 Nairobi
  const onNewDay = vi.fn();
  render(<Watcher onNewDay={onNewDay} />);
  act(() => vi.advanceTimersByTime(60_000)); // 23:59
  expect(onNewDay).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(90_000)); // 00:00:30
  expect(onNewDay).toHaveBeenCalledOnce();
  act(() => vi.advanceTimersByTime(120_000));
  expect(onNewDay).toHaveBeenCalledOnce();
});
