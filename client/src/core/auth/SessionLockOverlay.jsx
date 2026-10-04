import { SESSION_EXPIRED_MESSAGE } from "../api/client";
import { useEffect, useRef, useState } from "react";
import { LockKeyhole, Timer } from "lucide-react";
import { PasswordField } from "../../components/forms/PasswordField";
import { FormError } from "../../components/forms/FormNotice";

export function SessionLockOverlay({ locked, seconds, username, busy, error, onStay, onUnlock, onLogout }) {
  const panel = useRef(null);
  const [password, setPassword] = useState("");
  useEffect(() => {
    const previous = document.activeElement;
    const bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.querySelector(locked ? "input" : "button")?.focus();
    return () => { document.body.style.overflow = bodyOverflow; previous?.focus?.(); };
  }, [locked]);
  useEffect(() => {
    if (locked && !busy && error) panel.current?.querySelector("input")?.focus();
  }, [locked, busy, error]);
  function trapFocus(event) {
    if (event.key === "Escape") { event.preventDefault(); return; }
    if (event.key !== "Tab") return;
    const nodes = [...panel.current.querySelectorAll("button:not(:disabled), input:not(:disabled), a[href]")];
    if (!nodes.length) { event.preventDefault(); return; }
    if (event.shiftKey && document.activeElement === nodes[0]) {
      event.preventDefault(); nodes.at(-1).focus();
    } else if (!event.shiftKey && document.activeElement === nodes.at(-1)) {
      event.preventDefault(); nodes[0].focus();
    }
  }
  return <div className="sessionLockBackdrop">
    <section ref={panel} className="sessionLockCard" role="dialog" aria-modal="true" aria-labelledby="session-lock-title" aria-describedby="session-lock-description" onKeyDown={trapFocus}>
      <span className="sessionLockIcon">{locked ? <LockKeyhole size={28} /> : <Timer size={28} />}</span>
      <span className="eyebrow">{username}</span>
      <h1 id="session-lock-title">{locked ? "Workspace locked" : "Still working?"}</h1>
      <p id="session-lock-description">{locked ? `${SESSION_EXPIRED_MESSAGE} Continue where you left off.` : "Your workspace has been idle. Stay logged in to continue, or it will lock when the countdown ends."}</p>
      {!locked && <p className="sessionCountdown" role="timer" aria-label="Seconds until workspace locks">{Math.max(0, seconds)}<small>seconds remaining</small></p>}
      {locked ? <form onSubmit={async event => { event.preventDefault(); const value = password; setPassword(""); await onUnlock(value); }}>
        <PasswordField name="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} disabled={busy} />
        <button type="submit" disabled={busy}>{busy ? "Unlocking…" : "Unlock"}</button>
        <FormError title="Could not unlock." message={error} />
      </form> : <><button type="button" onClick={onStay} disabled={busy}>{busy ? "Renewing session…" : "Stay logged in"}</button><FormError message={error} /></>}
      <button type="button" className="secondary" disabled={busy} onClick={onLogout}>Log out instead</button>
      <small>Your current page stays open while the workspace is locked.</small>
    </section>
  </div>;
}
