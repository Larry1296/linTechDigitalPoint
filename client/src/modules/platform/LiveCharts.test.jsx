import { render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { LiveDashboard } from "./LiveCharts";

const plainMatchMedia = window.matchMedia;
beforeEach(() => {
  // A visitor who has asked for reduced motion: the charts hold still and show their numbers straight away.
  window.matchMedia = (query) => ({ matches: query.includes("prefers-reduced-motion"), addEventListener: () => undefined, removeEventListener: () => undefined });
  // An endless update loop is reported by React as "Maximum update depth exceeded"; failing on it stops the loop.
  vi.spyOn(console, "error").mockImplementation((message, ...rest) => {
    if (String(message).includes("Maximum update depth")) throw new Error(String(message));
    return rest;
  });
});
afterEach(() => { window.matchMedia = plainMatchMedia; vi.restoreAllMocks(); });

test("with reduced motion the live charts settle when the page around them re-renders", () => {
  // The tiles once set state on every render (a new array of the same numbers each time). It began at the first
  // re-render, such as a page change from / to /pricing/, never stopped, and left no time for the next page change:
  // links on the home page did nothing.
  const { rerender } = render(<LiveDashboard />);
  expect(() => rerender(<LiveDashboard />)).not.toThrow();
  expect(console.error).not.toHaveBeenCalledWith(expect.stringContaining("Maximum update depth"));
});
