import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

// The navbar the chat must never cover: the workspace topbar or the public site's navigation.
const NAVBARS = ".workspaceTopbar, .saasNav";
const GAP = 12;
const STEP = 40;
// Phones already get a full-width panel; resizing is for larger screens.
const resizable = () => window.innerWidth > 520;

function read(key) {
  try { const size = JSON.parse(localStorage.getItem(key)); return size?.width > 0 && size?.height > 0 ? size : null; } catch { return null; }
}
function write(key, size) {
  try { if (size) localStorage.setItem(key, JSON.stringify(size)); else localStorage.removeItem(key); } catch { /* private mode: the size is not kept */ }
}

/**
 * A chat panel anchored at the bottom right that can grow up and to the left: from its usual size (the smallest it
 * gets) to about half the screen's width and up to just below the navbar, which it never hides. The chosen size is
 * kept in this browser. Returns the panel ref, its inline style, a pointer/keyboard handler for the corner grip, and
 * maximise/restore.
 */
export function useResizablePanel(key, open) {
  const panel = useRef(null);
  const smallest = useRef(null);
  const [size, setSize] = useState(() => read(key));

  const limits = useCallback(() => {
    const element = panel.current;
    const min = smallest.current || { width: 0, height: 0 };
    if (!element) return { min, max: min };
    const bottom = element.getBoundingClientRect().bottom;
    const navbar = [...document.querySelectorAll(NAVBARS)].reduce((low, bar) => Math.max(low, bar.getBoundingClientRect().bottom), 0);
    return { min, max: { width: Math.max(min.width, window.innerWidth / 2), height: Math.max(min.height, bottom - navbar - GAP) } };
  }, []);
  const clamp = useCallback((next) => {
    if (!next) return null;
    const { min, max } = limits();
    // A maximised panel follows the largest size the window allows, also after the window changes.
    if (next.maximised) return { width: Math.round(max.width), height: Math.round(max.height), maximised: true };
    const fitted = { width: Math.round(Math.min(Math.max(next.width, min.width), max.width)),
      height: Math.round(Math.min(Math.max(next.height, min.height), max.height)) };
    return fitted.width <= min.width && fitted.height <= min.height ? null : fitted;
  }, [limits]);
  const choose = useCallback((next) => { const fitted = clamp(next); setSize(fitted); write(key, fitted); }, [clamp, key]);

  // The usual size comes from the stylesheet; measure it while no size is chosen, so it is the floor.
  useLayoutEffect(() => {
    if (!open || !panel.current) return;
    if (!size || !smallest.current) {
      const style = panel.current.style;
      const saved = [style.width, style.height];
      style.width = ""; style.height = "";
      smallest.current = { width: panel.current.offsetWidth, height: panel.current.offsetHeight };
      [style.width, style.height] = saved;
    }
    if (size) { const fitted = clamp(size); if (fitted?.width !== size.width || fitted?.height !== size.height || !fitted?.maximised !== !size.maximised) setSize(fitted); }
  }, [open, size, clamp]);
  // A smaller window shrinks a large panel so it still stays under the navbar.
  useEffect(() => {
    if (!open) return undefined;
    const fit = () => setSize((current) => clamp(current));
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [open, clamp]);

  const current = () => size || smallest.current || { width: 0, height: 0 };
  const startDrag = (event) => {
    if (!resizable()) return;
    event.preventDefault();
    const start = { x: event.clientX, y: event.clientY, ...current() };
    let latest = null;
    const moveTo = (e) => { latest = clamp({ width: start.width + start.x - e.clientX, height: start.height + start.y - e.clientY }); setSize(latest); };
    const stop = () => {
      window.removeEventListener("pointermove", moveTo);
      window.removeEventListener("pointerup", stop);
      write(key, latest);
    };
    window.addEventListener("pointermove", moveTo);
    window.addEventListener("pointerup", stop);
  };
  const onGripKey = (event) => {
    const change = { ArrowLeft: [STEP, 0], ArrowRight: [-STEP, 0], ArrowUp: [0, STEP], ArrowDown: [0, -STEP] }[event.key];
    if (!change) return;
    event.preventDefault();
    const { width, height } = current();
    choose({ width: width + change[0], height: height + change[1] });
  };
  const maximised = Boolean(size?.maximised);
  const toggleMaximised = () => choose(maximised ? null : { maximised: true });
  const style = size && resizable() ? { width: size.width, height: size.height, maxWidth: "none", maxHeight: "none" } : undefined;
  return { panel, style, startDrag, onGripKey, maximised, toggleMaximised };
}
