import { useEffect, useRef } from "react";

// Every successful change (a sale, a payment, a stock adjustment…) is announced here, in this tab and in the
// user's other open tabs, so any page showing figures can fetch them again without a manual reload.
const EVENT = "lintech:data-changed";
const CHANNEL = "lintech-data";
let channel;
function broadcast() {
  if (channel === undefined) channel = typeof BroadcastChannel === "function" ? new BroadcastChannel(CHANNEL) : null;
  return channel;
}

export function announceDataChanged(path) {
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { path } }));
  try { broadcast()?.postMessage({ path }); } catch { /* another tab may be closing */ }
}

// Calls `load` again after any change in the app (this tab or another), and when the page comes back into
// view, which is how changes made on other devices are picked up. Optional `pollMs` also refreshes on a timer.
// Bursts (a change that triggers several saves) are merged into one refresh.
export function useLiveRefresh(load, { pollMs } = {}) {
  const latest = useRef(load);
  useEffect(() => { latest.current = load; });
  useEffect(() => {
    let timer;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(() => { Promise.resolve(latest.current()).catch(() => {}); }, 250);
    };
    const whenVisible = () => { if (!document.hidden) refresh(); };
    window.addEventListener(EVENT, refresh);
    window.addEventListener("focus", whenVisible);
    document.addEventListener("visibilitychange", whenVisible);
    const other = typeof BroadcastChannel === "function" ? new BroadcastChannel(CHANNEL) : null;
    if (other) other.onmessage = refresh;
    const poll = pollMs ? setInterval(whenVisible, pollMs) : null;
    return () => {
      clearTimeout(timer);
      if (poll) clearInterval(poll);
      window.removeEventListener(EVENT, refresh);
      window.removeEventListener("focus", whenVisible);
      document.removeEventListener("visibilitychange", whenVisible);
      other?.close();
    };
  }, [pollMs]);
}
