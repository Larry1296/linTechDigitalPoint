import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { PasswordField } from "../../components/forms/PasswordField";
import { FormError } from "../../components/forms/FormNotice";
import { Loading } from "../../components/States";
import { PinField } from "./PinField";

const STATUS = "/api/v1/auth/protected/";
// A private page left untouched this long locks again, so figures are not left on a screen customers can see.
export const PRIVATE_IDLE_MS = 5 * 60 * 1000;
const pageOf = (pathname) => (pathname.startsWith("/admin/investments") ? "investments" : "mpesa");

// The private pages (M-Pesa and investments) are the only pages that lock by themselves. Each opens with the person's
// lock PIN, or with a PIN of its own when they set one in Settings; one PIN opens every page that shares it. An open
// page locks again after five minutes untouched, with "Lock now", or when the workspace locks or they sign out.
export function ProtectedPages() {
  const page = pageOf(useLocation().pathname);
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const check = useCallback(() => api(STATUS).then((data) => setState(data.protected)).catch((err) => setError(err.message)), []);
  const lockNow = useCallback(() => api("/api/v1/auth/protected/lock/", { method: "POST" }).then((data) => setState(data.protected)).catch(() => {}), []);
  useEffect(() => {
    void check();
    const relock = () => void check();
    window.addEventListener("protected-locked", relock);
    window.addEventListener("session-unlocked", relock);
    return () => { window.removeEventListener("protected-locked", relock); window.removeEventListener("session-unlocked", relock); };
  }, [check]);
  const open = Boolean(state?.pages[page]?.unlocked);
  useIdleLock(open, lockNow);
  if (!state) return error ? <FormError message={error} /> : <Loading />;
  if (open) return <>
    <p className="protectedBar"><ShieldCheck size={16} aria-hidden="true" /> Private page. It locks after 5 minutes untouched.
      <button type="button" className="linkButton" onClick={() => void lockNow()}>Lock now</button></p>
    <Outlet />
  </>;
  return <PrivatePageLock page={page} state={state} onOpen={setState} />;
}

// Locks the open private page once nobody has touched the screen or keyboard for PRIVATE_IDLE_MS, also while the tab
// was hidden or the computer asleep (the time is measured, not counted down).
function useIdleLock(open, lockNow) {
  const last = useRef(0);
  useEffect(() => {
    if (!open) return;
    last.current = Date.now();
    const touched = (event) => { if (event.isTrusted) last.current = Date.now(); };
    const check = () => { if (Date.now() - last.current >= PRIVATE_IDLE_MS) void lockNow(); };
    const events = ["pointerdown", "keydown", "wheel", "touchstart"];
    for (const event of events) window.addEventListener(event, touched, { passive: true, capture: true });
    const timer = window.setInterval(check, 5000);
    document.addEventListener("visibilitychange", check);
    return () => {
      for (const event of events) window.removeEventListener(event, touched, { capture: true });
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, [open, lockNow]);
}

function PrivatePageLock({ page, state, onOpen }) {
  const info = state.pages[page];
  // "pin" enters the PIN; "password" opens with the sign-in password (forgotten PIN, or too many wrong ones);
  // "set" is the first time, when there is no lock PIN yet.
  const [mode, setMode] = useState(!state.has_pin ? "set" : state.needs_password ? "password" : "pin");
  const [form, setForm] = useState({ password: "", pin: "", again: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (state.needs_password && mode === "pin") setMode("password"); }, [state.needs_password, mode]);
  const field = (key) => ({ value: form[key], onChange: (event) => setForm({ ...form, [key]: event.target.value }), readOnly: busy, required: true });
  async function send(body) {
    setBusy(true); setError("");
    try {
      const data = await api("/api/v1/auth/protected/unlock/", { method: "POST", body: JSON.stringify({ page, ...body }) });
      onOpen(data.protected);
      return true;
    } catch (err) {
      if (err.data?.protected) onOpen(err.data.protected);
      setError(err.message);
      return false;
    } finally { setBusy(false); }
  }
  async function setPin(event) {
    event.preventDefault();
    if (!/^\d{4,6}$/.test(form.pin)) { setError("A PIN is 4 to 6 digits."); return; }
    if (form.pin !== form.again) { setError("The two PINs are not the same."); return; }
    setBusy(true); setError("");
    try {
      await api("/api/v1/auth/lock-pin/", { method: "POST", body: JSON.stringify({ password: form.password, pin: form.pin }) });
    } catch (err) { setError(err.message); setBusy(false); return; }
    setBusy(false);
    await send({ pin: form.pin });
  }
  const titles = { set: "Set your lock PIN", pin: `Enter your PIN for ${info.label}`, password: `Open ${info.label} with your password` };
  const notes = {
    set: "M-Pesa and investments are private pages. Choose a PIN of 4 to 6 digits: it opens them, and your workspace after you lock it. In Settings you can give each private page a PIN of its own.",
    pin: info.own_pin ? `${info.label} has a PIN of its own.` : "Your lock PIN opens the private pages.",
    password: state.needs_password ? "Too many wrong PINs. Enter your sign-in password to open the private pages." : "Your sign-in password opens every private page.",
  };
  return <section className="sessionLockCard protectedCard" aria-labelledby="protected-title">
    <span className="sessionLockIcon"><ShieldCheck size={28} /></span>
    <h1 id="protected-title">{titles[mode]}</h1>
    <p>{notes[mode]}</p>
    {mode === "pin" && <>
      <PinField length={info.pin_length} busy={busy} error={error} onPin={(pin) => send({ pin })} />
      <button type="button" className="linkButton" disabled={busy} onClick={() => { setMode("password"); setError(""); }}>Forgot your PIN? Use your sign-in password</button>
      {!info.own_pin && <small>Give this page a PIN of its own in <Link to="/admin/settings">Settings</Link>.</small>}
    </>}
    {mode === "password" && <form onSubmit={(event) => { event.preventDefault(); void send({ password: form.password }); }}>
      <PasswordField label="Your sign-in password" autoComplete="current-password" autoFocus {...field("password")} />
      <button type="submit" disabled={busy}>{busy ? "Checking…" : "Open"}</button>
      <FormError title="Could not open." message={error} />
      {!state.needs_password && <button type="button" className="secondary" disabled={busy} onClick={() => { setMode("pin"); setError(""); }}>Back to PIN</button>}
    </form>}
    {mode === "set" && <form onSubmit={setPin}>
      <PasswordField label="Your sign-in password" autoComplete="current-password" autoFocus {...field("password")} />
      <PasswordField label="New PIN (4 to 6 digits)" inputMode="numeric" autoComplete="off" maxLength={6} {...field("pin")} />
      <PasswordField label="New PIN again" inputMode="numeric" autoComplete="off" maxLength={6} {...field("again")} />
      <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save and open"}</button>
      <FormError title="Could not save." message={error} />
    </form>}
  </section>;
}
