import { SESSION_EXPIRED_MESSAGE } from "../api/client";
import { useEffect, useRef, useState } from "react";
import { LockKeyhole, Timer } from "lucide-react";
import { PasswordField } from "../../components/forms/PasswordField";
import { FormError } from "../../components/forms/FormNotice";

// How long typing must pause before a typed password is tried by itself, the shortest password worth trying, and how
// many automatic tries one lock allows: the server blocks unlocking for a minute after 5 wrong passwords, so automatic
// tries never use up more than two of them and never repeat the same text.
const PAUSE_MS = 1000;
const SHORTEST = 8;
const AUTO_TRIES = 2;

export function SessionLockOverlay({ locked, seconds, username, busy, error, onStay, onUnlock, onLogout }) {
  const panel = useRef(null);
  const [password, setPassword] = useState("");
  const auto = useRef({ tried: new Set(), timer: null });
  // The workspace opens by itself once the right password is in: at once when it is filled in all at once (a saved
  // password, autofill or paste), otherwise after a short pause in typing. A wrong automatic try stays quiet.
  const tryQuietly = async (value) => {
    const state = auto.current;
    if (!locked || busy || value.length < SHORTEST || state.tried.has(value) || state.tried.size >= AUTO_TRIES) return;
    state.tried.add(value);
    const opened = await onUnlock(value, { quiet: true });
    if (!opened) panel.current?.querySelector("input")?.focus();
  };
  const change = (event) => {
    const value = event.target.value;
    const filled = value.length - password.length > 2;  // more than a keystroke at once: autofill or paste
    setPassword(value);
    clearTimeout(auto.current.timer);
    if (filled) void tryQuietly(value);
    else auto.current.timer = setTimeout(() => void tryQuietly(value), PAUSE_MS);
  };
  useEffect(() => () => clearTimeout(auto.current.timer), []);
  useEffect(() => { auto.current.tried = new Set(); }, [locked]);
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
      {locked ? <form onSubmit={async event => { event.preventDefault(); clearTimeout(auto.current.timer); const value = password; setPassword(""); await onUnlock(value); }}>
        <PasswordField name="password" autoComplete="current-password" required value={password} onChange={change} readOnly={busy} />
        <button type="submit" disabled={busy}>{busy ? "Unlocking…" : "Unlock"}</button>
        <FormError title="Could not unlock." message={error} />
      </form> : <><button type="button" onClick={onStay} disabled={busy}>{busy ? "Renewing session…" : "Stay logged in"}</button><FormError message={error} /></>}
      <button type="button" className="secondary" disabled={busy} onClick={onLogout}>Log out instead</button>
      <small>Your current page stays open while the workspace is locked.</small>
    </section>
  </div>;
}
