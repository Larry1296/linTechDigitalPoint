import { expect, it } from "vitest";
import { preventPinchZoom } from "./pinchZoom";

it("cancels touchpad pinch-zoom but leaves ordinary scrolling alone", () => {
  const stop = preventPinchZoom();
  const pinch = new WheelEvent("wheel", { deltaY: -40, ctrlKey: true, cancelable: true });
  const scroll = new WheelEvent("wheel", { deltaY: 120, cancelable: true });
  const gesture = new Event("gesturestart", { cancelable: true });
  window.dispatchEvent(pinch); window.dispatchEvent(scroll); window.dispatchEvent(gesture);
  expect([pinch.defaultPrevented, scroll.defaultPrevented, gesture.defaultPrevented]).toEqual([true, false, true]);
  stop();
  const after = new WheelEvent("wheel", { deltaY: -40, ctrlKey: true, cancelable: true });
  window.dispatchEvent(after);
  expect(after.defaultPrevented).toBe(false);
});
