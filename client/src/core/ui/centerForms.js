// A form that opens because the person did something (Add money, Record payment, Edit…) is brought to the middle of
// the screen and its first field is ready to type in, wherever it opens on the page. Only forms that appear just after
// a click or key press on the same page: a page opened from the menu keeps its own scroll, and pop-up dialogs are
// already centred. A form can opt out with data-no-center on it or a container.
const WINDOW_MS = 1500;
const SKIP = "[role='dialog'], .swal2-container, .sessionLockBackdrop, [data-no-center]";
const FIELDS = "input:not([type='hidden']):not([disabled]):not([readonly]), select:not([disabled]), textarea:not([disabled]):not([readonly])";

export function center(form) {
  if (typeof form.scrollIntoView !== "function") return;
  const tall = form.getBoundingClientRect().height > window.innerHeight * 0.9;
  const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  form.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: tall ? "start" : "center" });
  if (!form.contains(document.activeElement)) form.querySelector(FIELDS)?.focus({ preventScroll: true });
}

export function centerNewForms() {
  if (typeof MutationObserver === "undefined") return () => {};
  let last = { at: -Infinity, path: "" };
  const acted = (event) => {
    if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
    last = { at: performance.now(), path: window.location.pathname };
  };
  window.addEventListener("pointerdown", acted, true);
  window.addEventListener("keydown", acted, true);
  const observer = new MutationObserver((changes) => {
    if (performance.now() - last.at > WINDOW_MS || window.location.pathname !== last.path) return;
    for (const change of changes) {
      for (const node of change.addedNodes) {
        if (node.nodeType !== 1) continue;
        const form = node.matches("form") ? node : node.querySelector("form");
        if (!form || form.closest(SKIP)) continue;
        last = { at: -Infinity, path: "" };  // one form per action
        requestAnimationFrame(() => center(form));
        return;
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  return () => {
    observer.disconnect();
    window.removeEventListener("pointerdown", acted, true);
    window.removeEventListener("keydown", acted, true);
  };
}
