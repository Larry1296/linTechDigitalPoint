import "@testing-library/jest-dom";
import { setOutcomeOverlays } from "./core/ui/outcome";

// Pages are tested for their own messages; the full-screen outcome overlay has its own tests.
setOutcomeOverlays(false);
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: () => ({
    matches: false,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }),
});
