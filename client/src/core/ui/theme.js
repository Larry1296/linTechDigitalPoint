import { useEffect, useSyncExternalStore } from "react";

const eventName = "appearance-changed";
// Every page load starts from the system theme; a manual choice lasts only until reload.
let selected = "system";
try {
  localStorage.removeItem("theme");
} catch {
  /* Storage may be disabled. */
}
function preference() {
  return selected;
}
function subscribe(listener) {
  window.addEventListener(eventName, listener);
  return () => window.removeEventListener(eventName, listener);
}
export function applyTheme() {
  document.documentElement.dataset.theme = selected === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : selected;
}
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, preference, () => "system");
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    applyTheme();
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [theme]);
  return [theme, (value) => {
    selected = ["light", "dark"].includes(value) ? value : "system";
    applyTheme();
    window.dispatchEvent(new Event(eventName));
  }];
}
export function ThemeSync() {
  useTheme();
  return null;
}
