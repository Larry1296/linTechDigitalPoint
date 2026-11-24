import { SESSION_EXPIRED_MESSAGE } from "../api/client";
import { useEffect, useRef, useState } from "react";
import { LockKeyhole } from "lucide-react";
import { deviceCheck } from "./biometric";
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
export function SessionLockOverlay({ username, pinLength, biometric = false, askAtOnce = false, busy, error, onUnlock, onPin, onBiometric, onLogout }) {
  const panel = useRef(null);
  const { name: check, Icon: CheckIcon } = deviceCheck();
  const [password, setPassword] = useState("");
  // What the person chose instead of the first choice: "pin" or "password".
  const [choice, setChoice] = useState(null);
  const mode = choice === "password" ? "password" : choice === "pin" && pinLength ? "pin" : biometric ? "biometric" : pinLength ? "pin" : "password";
  const byPin = mode === "pin";
  // Like a phone's own lock screen, the device's fingerprint or face prompt opens by itself, so a touch of the sensor
  // (or a look) is all it takes: when the lock screen shows on a page opened or reloaded while locked (askAtOnce; not
  // the moment the person presses Lock, when they are walking away), when they come back to the page or app, and
  // when they tap anywhere on the lock screen. A closed or failed prompt stays closed until they leave and come
  // back, or tap: it never asks again by itself in a loop. The button is there for browsers that need a tap.
  const asking = useRef({ running: false, paused: false, atOnce: false });
  useEffect(() => {
    if (mode !== "biometric") return undefined;
    const state = asking.current;
    const ask = async (byTap) => {
      if (busy || state.running || (!byTap && state.paused)) return;
      state.running = true;
      const opened = await onBiometric?.();
      state.running = false;
      if (!opened) state.paused = true;
    };
    const visibility = () => {
      if (document.visibilityState === "hidden") state.paused = false;
      else void ask(false);
    };
    const focus = () => void ask(false);
    const tap = (event) => { if (!event.target.closest?.("button, a, input, select, textarea, label")) void ask(true); };
    let soon;
    if (askAtOnce && !state.atOnce) { state.atOnce = true; soon = setTimeout(() => void ask(false), 0); }
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("focus", focus);
    document.addEventListener("pointerdown", tap);
    return () => {
      clearTimeout(soon);
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("focus", focus);
      document.removeEventListener("pointerdown", tap);
    };
  }, [mode, busy, askAtOnce, onBiometric]);
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
      <p id="session-lock-description">{mode === "biometric" ? `Use ${check} to continue where you left off: touch the sensor or look at the device when it asks, or tap the screen.`
        : byPin ? "Enter your PIN to continue where you left off." : `${SESSION_EXPIRED_MESSAGE} Continue where you left off.`}</p>
      {mode === "biometric" ? <>
        <button type="button" className="biometricUnlock" disabled={busy} onClick={() => void onBiometric()}>
          <CheckIcon size={22} aria-hidden="true" />{busy ? "Unlocking…" : `Unlock with ${check}`}
        </button>
        <FormError title="Could not unlock." message={error} />
        {pinLength && <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("pin")}>Use your PIN instead</button>}
        <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("password")}>Use your password instead</button>
      </> : byPin ? <>
        <PinField length={pinLength} busy={busy} error={error} onPin={onPin} />
        {biometric && <button type="button" className="linkButton" disabled={busy} onClick={() => { setChoice(null); void onBiometric?.(); }}>Use {check} instead</button>}
        <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("password")}>Use your password instead</button>
      </> : <form onSubmit={async event => { event.preventDefault(); const value = password; setPassword(""); await onUnlock(value); }}>
        <PasswordField name="password" autoComplete="current-password" required value={password} onChange={change} readOnly={busy} />
        <button type="submit" disabled={busy}>{busy ? "Unlocking…" : "Unlock"}</button>
        <FormError title="Could not unlock." message={error} />
        {biometric && <button type="button" className="linkButton" disabled={busy} onClick={() => { setChoice(null); void onBiometric?.(); }}>Use {check} instead</button>}
        {pinLength ? <button type="button" className="linkButton" disabled={busy} onClick={() => setChoice("pin")}>Use your PIN instead</button>
          : !biometric && <small>Set a lock PIN in Settings to unlock with a few digits instead.</small>}
      </form>}
      <button type="button" className="secondary" disabled={busy} onClick={onLogout}>Log out instead</button>
      <small>Your current page stays open while the workspace is locked.</small>
    </section>
  </div>;
}
