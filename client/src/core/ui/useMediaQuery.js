import { useSyncExternalStore } from "react";

// True while the media query matches. Where matchMedia is missing (tests, old browsers) it is false.
export function useMediaQuery(query) {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia?.(query);
      media?.addEventListener("change", onChange);
      return () => media?.removeEventListener("change", onChange);
    },
    () => Boolean(window.matchMedia?.(query).matches),
    () => false,
  );
}
