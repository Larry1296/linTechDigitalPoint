import { useEffect, useRef, useState } from "react";
import { Timer } from "lucide-react";

// How long the warning shows before a lock that comes by itself (the session's 12 hours ending, or a private page left
// untouched), so whoever is at the screen can keep it open.
export const WARNING_MS = 30 * 1000;

// The 30-second warning before a lock. It counts down from 30 to 0 by the clock (a sleeping tab that wakes late shows
// the right number, and the lock still comes on time from the caller). Only "Keep it open" stops the lock: touching
// elsewhere does not, so the screen locks as expected when nobody answers. "Lock now" locks at once.
export function LockCountdown({ endsAt, title, message, stayLabel = "Keep it open", onStay, onLockNow, busy = false }) {
  const [now, setNow] = useState(() => Date.now());
  const stay = useRef(null);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => { stay.current?.focus(); }, []);
  const seconds = Math.max(0, Math.ceil((endsAt - now) / 1000));
  return <div className="sessionLockBackdrop lockWarningBackdrop">
    <section className="sessionLockCard lockWarningCard" role="alertdialog" aria-modal="true" aria-labelledby="lock-warning-title"
      aria-describedby="lock-warning-description" onKeyDown={(event) => { if (event.key === "Escape") event.preventDefault(); }}>
      <span className="sessionLockIcon"><Timer size={28} /></span>
      <h1 id="lock-warning-title">{title}</h1>
      <p className="sessionCountdown" aria-live="off">{seconds}<small>{seconds === 1 ? "second" : "seconds"}</small></p>
      <p id="lock-warning-description">{message}</p>
      <button type="button" ref={stay} disabled={busy} onClick={onStay}>{busy ? "Keeping it open…" : stayLabel}</button>
      <button type="button" className="secondary" disabled={busy} onClick={onLockNow}>Lock now</button>
    </section>
  </div>;
}
