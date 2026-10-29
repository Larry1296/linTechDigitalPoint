import { SESSION_EXPIRED_MESSAGE } from "../api/client";
import { useEffect, useRef, useState } from "react";
import { LockKeyhole } from "lucide-react";
import { PasswordField } from "../../components/forms/PasswordField";
import { FormError } from "../../components/forms/FormNotice";
import { knownPasswordLength } from "./passwordLength";
import { PinField } from "./PinField";

// The shortest password worth trying when its length is not known, and how many automatic tries one lock allows: the server blocks unlocking for a
// minute after 5 wrong passwords, so automatic tries never use up more than two of them and never repeat the same text.
const SHORTEST = 8;
const AUTO_TRIES = 2;

// The workspace locks only when the person locks it (or at the end of its 12 hours). A lock they made opens with their
// lock PIN; the password opens any lock, and is needed after too many wrong PINs or when the session ends.
export function SessionLockOverlay({ username, pinLength, busy, error, onUnlock, onPin, onLogout }) {
  const panel = useRef(null);
  const [password, setPassword] = useState("");
  const [usePassword, setUsePassword] = useState(false);
  const byPin = Boolean(pinLength) && !usePassword;
  const auto = useRef({ tried: new Set() });
  // The workspace opens by itself once the right password is in: when it is filled in all at once (a saved password,
  // autofill or paste), or when what is typed reaches the length of the password this tab last signed in with, never
  // part-way through typing. When that length is not known, typing waits for Enter. A wrong automatic try stays quiet.
  const tryQuietly = async (value) => {
    const state = auto.current;
    if (busy || (value.length < SHORTEST && value.length !== knownPasswordLength()) || state.tried.has(value) || state.tried.size >= AUTO_TRIES) return;
    state.tried.add(value);
    const opened = await onUnlock(value, { quiet: true });
    if (!opened) panel.current?.querySelector("input")?.focus();
  };
  const change = (event) => {
    const value = event.target.value;
    const filled = value.length - password.length > 2;  // more than a keystroke at once: autofill or paste
    setPassword(value);
    if (filled || value.length === knownPasswordLength()) void tryQuietly(value);
  };
  useEffect(() => {
    const previous = document.activeElement;
    const bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.querySelector("input")?.focus();
    return () => { document.body.style.overflow = bodyOverflow; previous?.focus?.(); };
  }, []);
  useEffect(() => {
    if (!busy && error) panel.current?.querySelector("input")?.focus();
  }, [busy, error]);
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
      <span className="sessionLockIcon"><LockKeyhole size={28} /></span>
      <span className="eyebrow">{username}</span>
      <h1 id="session-lock-title">Workspace locked</h1>
      <p id="session-lock-description">{byPin ? "Enter your PIN to continue where you left off." : `${SESSION_EXPIRED_MESSAGE} Continue where you left off.`}</p>
      {byPin ? <>
        <PinField length={pinLength} busy={busy} error={error} onPin={onPin} />
        <button type="button" className="linkButton" disabled={busy} onClick={() => setUsePassword(true)}>Use your password instead</button>
      </> : <form onSubmit={async event => { event.preventDefault(); const value = password; setPassword(""); await onUnlock(value); }}>
        <PasswordField name="password" autoComplete="current-password" required value={password} onChange={change} readOnly={busy} />
        <button type="submit" disabled={busy}>{busy ? "Unlocking…" : "Unlock"}</button>
        <FormError title="Could not unlock." message={error} />
        {!pinLength && <small>Set a lock PIN in Settings to unlock with a few digits instead.</small>}
      </form>}
      <button type="button" className="secondary" disabled={busy} onClick={onLogout}>Log out instead</button>
      <small>Your current page stays open while the workspace is locked.</small>
    </section>
  </div>;
}
