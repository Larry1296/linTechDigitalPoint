import { useEffect } from "react";

/** Keep wheel/trackpad scrolling from stepping a focused native number input. */
export function usePreventNumberScroll() {
  useEffect(() => {
    const preventNumberStep = (event) => {
      const input = event.target;
      if (
        input instanceof HTMLInputElement &&
        input.type === "number" &&
        input === document.activeElement
      ) {
        // Blur before the browser's default wheel action. Do not cancel the
        // event: the page should still scroll normally.
        input.blur();
      }
    };
    document.addEventListener("wheel", preventNumberStep, {
      capture: true,
      passive: true,
    });
    return () => document.removeEventListener("wheel", preventNumberStep, true);
  }, []);
}
