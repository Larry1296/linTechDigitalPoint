import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PhotoCarousel } from "./PhotoCarousel";

const slides = [
  { src: "/a.jpg", alt: "Shop counter", title: "Shop" },
  { src: "/b.jpg", alt: "Checkout", title: "Point of sale" },
  { src: "/c.jpg", alt: "Reports", title: "Reports" },
];
const current = () => screen.getByTestId("caption").textContent;
const show = () => render(<PhotoCarousel slides={slides} label="Showcase">{(slide) => <p data-testid="caption">{slide.title}</p>}</PhotoCarousel>);

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

it("moves to the next photo every four seconds and wraps around", () => {
  show();
  expect(current()).toBe("Shop");
  act(() => vi.advanceTimersByTime(3999));
  expect(current()).toBe("Shop");
  act(() => vi.advanceTimersByTime(1));
  expect(current()).toBe("Point of sale");
  act(() => vi.advanceTimersByTime(4000));
  expect(current()).toBe("Reports");
  act(() => vi.advanceTimersByTime(4000));
  expect(current()).toBe("Shop");
  expect(screen.getByRole("button", { name: "Show slide 1: Shop" })).toHaveAttribute("aria-current", "true");
});

it("stays on a photo while paused, and a dot jumps straight to its photo", () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "Pause slideshow" }));
  act(() => vi.advanceTimersByTime(20000));
  expect(current()).toBe("Shop");
  fireEvent.click(screen.getByRole("button", { name: "Show slide 3: Reports" }));
  expect(current()).toBe("Reports");
  fireEvent.click(screen.getByRole("button", { name: "Play slideshow" }));
  act(() => vi.advanceTimersByTime(4000));
  expect(current()).toBe("Shop");
});

it("waits for its start delay before the first switch", () => {
  render(<PhotoCarousel slides={slides} label="Showcase" startDelay={700}>{(slide) => <p data-testid="caption">{slide.title}</p>}</PhotoCarousel>);
  act(() => vi.advanceTimersByTime(4000));
  expect(current()).toBe("Shop");
  act(() => vi.advanceTimersByTime(700));
  expect(current()).toBe("Point of sale");
  act(() => vi.advanceTimersByTime(4000));
  expect(current()).toBe("Reports");
});
