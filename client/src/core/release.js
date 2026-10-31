import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

// A tab opened before a release keeps running the old page against the new server, and shows screens that no longer
// exist. The page itself is never cached, so the name of its main script (it carries a hash of the build) tells
// whether a newer release is out. When it is, the tab reloads at once if nothing has been typed on the page (a PIN
// screen, a list), otherwise at the next move to another page, so nothing typed is lost.
const CHECK_EVERY_MS = 5 * 60 * 1000;
const scriptOf = (html) => html.match(/<script[^>]+type="module"[^>]+src="([^"]+)"/)?.[1] ?? null;
const running = () => document.querySelector('script[type="module"][src]')?.getAttribute("src") ?? null;

export async function newReleaseOut() {
  const current = running();
  if (!current || !current.includes("/assets/")) return false;  // the development server has no built files
  try {
    const response = await fetch("/", { cache: "no-store", headers: { Accept: "text/html" } });
    if (!response.ok) return false;
    const latest = scriptOf(await response.text());
    return Boolean(latest && latest !== current);
  } catch { return false; }
}

export function useReloadOnNewRelease() {
  const { pathname } = useLocation();
  const outdated = useRef(false);
  const first = useRef(true);
  const typed = useRef(false);
  useEffect(() => {
    const check = async () => {
      if (!outdated.current) outdated.current = await newReleaseOut();
      if (outdated.current && !typed.current) window.location.reload();
    };
    const typing = () => { typed.current = true; };
    document.addEventListener("input", typing, true);
    const visible = () => { if (!document.hidden) void check(); };
    const timer = window.setInterval(check, CHECK_EVERY_MS);
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("focus", visible);
    void check();
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("focus", visible);
      document.removeEventListener("input", typing, true);
    };
  }, []);
  useEffect(() => {
    typed.current = false;  // a new page: nothing typed on it yet
    if (first.current) { first.current = false; return; }
    if (outdated.current) window.location.reload();
  }, [pathname]);
}
