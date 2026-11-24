import { SESSION_EXPIRED_MESSAGE } from "../api/client";
import { useEffect, useRef, useState } from "react";
import { Fingerprint, LockKeyhole } from "lucide-react";
import { PasswordField } from "../../components/forms/PasswordField";
import { FormError } from "../../components/forms/FormNotice";
import { knownPasswordLength } from "./passwordLength";
import { PinField } from "./PinField";

// The shortest password worth trying when its length is not known, and how many automatic tries one lock allows: the server blocks unlocking for a
// minute after 5 wrong passwords, so automatic tries never use up more than two of them and never repeat the same text.
const SHORTEST = 8;
const AUTO_TRIES = 2;

// The workspace locks only when the person locks it (or at the end of its 12 hours). A lock they made opens with their
// lock PIN; the password opens any lock, and is needed after too many wrong PINs or when the session ends. On a device
// where the person turned on their fingerprint or face, that is the first choice for any lock (see AuthContext), and
// the PIN and password are the other choices.
export function SessionLockOverlay({ username, pinLength, biometric = false, busy, error, onUnlock, onPin, onBiometric, onLogout }) {
  const panel = useRef(null);
  const [password, setPassword] = useState("");
  // What the person chose instead of the first choice: "pin" or "password".
  const [choice, setChoice] = useState(null);
  const mode = choice === "password" ? "password" : choice === "pin" && pinLength ? "pin" : biometric ? "biometric" : pinLength ? "pin" : "password";
  const byPin = mode === "pin";
  // Coming back to a locked page (another app, another tab) asks for the fingerprint or face at once, where the
  // browser allows it without a tap; the button is there either way.
  useEffect(() => {
    if (mode !== "biometric" || busy) return undefined;
    const back = () => { if (document.visibilityState === "visible") void onBiometric?.(); };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [mode, busy, onBiometric]);
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
    panel.current?.querySelector("input, .biometricUnlock")?.focus();
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
      <p id="session-lock-description">{mode === "biometric" ? "Use your fingerprint or face to continue where you left off."
        : byPin ? "Enter your PIN to continue where you left off." : `${SESSION_EXPIRED_MESSAGE} Continue where you left off.`}</p>
      {mode === "biometric" ? <>
        <button type="button" className="biometricUnlock" disabled={busy} onClick={() => void onBiometric()}>
          <Fingerprint size={22} aria-hidden="true" />{busy ? "Unlocking…" : "Unlock with fingerprint or face"}
        </button>
        <FormError title="Could not unlock." message={error} />
        {pinLength && <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("pin")}>Use your PIN instead</button>}
        <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("password")}>Use your password instead</button>
      </> : byPin ? <>
        <PinField length={pinLength} busy={busy} error={error} onPin={onPin} />
        {biometric && <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice(null)}>Use fingerprint or face instead</button>}
        <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("password")}>Use your password instead</button>
      </> : <form onSubmit={async event => { event.preventDefault(); const value = password; setPassword(""); await onUnlock(value); }}>
        <PasswordField name="password" autoComplete="current-password" required value={password} onChange={change} readOnly={busy} />
        <button type="submit" disabled={busy}>{busy ? "Unlocking…" : "Unlock"}</button>
        <FormError title="Could not unlock." message={error} />
        {biometric && <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice(null)}>Use fingerprint or face instead</button>}
        {pinLength ? <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("pin")}>Use your PIN instead</button>
          : !biometric && <small>Set a lock PIN in Settings to unlock with a few digits instead.</small>}
      </form>}
      <button type="button" className="secondary" disabled={busy} onClick={onLogout}>Log out instead</button>
      <small>Your current page stays open while the workspace is locked.</small>
    </section>
  </div>;
}
