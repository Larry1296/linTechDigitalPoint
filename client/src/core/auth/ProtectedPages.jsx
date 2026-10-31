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

// The private pages (M-Pesa and investments) are the only pages that lock by themselves. Each opens only with a PIN,
// and each person has their own: the owner's, and each employee's for the pages the owner gave them, set by them the
// first time and reset only by the owner. Investments are the owner's alone. An open page locks again
// after five minutes untouched, with "Lock now", or when the workspace locks or they sign out.
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
  const owner = state.is_owner;
  const [form, setForm] = useState({ password: "", pin: "", again: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // A PIN is numbers only: anything else typed into a PIN box is dropped as it is typed.
  const field = (key) => ({ value: form[key], readOnly: busy, required: true,
    onChange: (event) => setForm({ ...form, [key]: key === "password" ? event.target.value : event.target.value.replace(/\D/g, "").slice(0, 6) }) });
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
  // The person sets their own PIN for the page the first time, confirmed with their sign-in password.
  async function setPin(event) {
    event.preventDefault();
    if (!/^\d{4,6}$/.test(form.pin)) { setError("A PIN is 4 to 6 numbers (0 to 9), with no letters."); return; }
    if (form.pin !== form.again) { setError("The two PINs are not the same."); return; }
    setBusy(true); setError("");
    try {
      await api("/api/v1/auth/lock-pin/", { method: "POST", body: JSON.stringify({ page, password: form.password, pin: form.pin }) });
    } catch (err) { setError(err.message); setBusy(false); return; }
    setBusy(false);
    await send({ pin: form.pin });
  }
  if (!info.allowed) return <section className="sessionLockCard protectedCard" aria-labelledby="protected-title">
    <span className="sessionLockIcon"><ShieldCheck size={28} /></span>
    <h1 id="protected-title">{info.kept_out === "hidden" ? `${info.label} is not open to you` : `${info.label} is for the business owner only`}</h1>
    <p>{info.kept_out === "hidden" ? "The business owner has not given you this page. Ask them if you need it." : "Only the owner of the business can open it, or someone they give it to."}</p>
  </section>;
  if (!info.pin_set) return <section className="sessionLockCard protectedCard" aria-labelledby="protected-title">
    <span className="sessionLockIcon"><ShieldCheck size={28} /></span>
    <h1 id="protected-title">{owner ? `Set the ${info.label} PIN` : `Set your ${info.label} PIN`}</h1>
    {info.can_set !== false ? <>
      <p>{info.label} is a private page: it opens only with your own PIN for it, 4 to 6 numbers, different from your lock PIN and any other page's.
        {owner ? " Each employee you give it to sets their own. You can change or reset yours in Settings."
          : " Keep it to yourself. If you forget it, the business owner resets it and you set a new one."}</p>
      <form onSubmit={setPin}>
        <PasswordField label="Your sign-in password" autoComplete="current-password" autoFocus {...field("password")} />
        <PasswordField label={`${info.label} PIN (4 to 6 numbers)`} inputMode="numeric" autoComplete="off" maxLength={6} {...field("pin")} />
        <PasswordField label="The PIN again" inputMode="numeric" autoComplete="off" maxLength={6} {...field("again")} />
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save and open"}</button>
        <FormError title="Could not save." message={error} />
      </form>
    </> : <p>Ask the business owner to reset your PIN, then set a new one here.</p>}
  </section>;
  const waiting = state.blocked_until && new Date(state.blocked_until) > new Date();
  return <section className="sessionLockCard protectedCard" aria-labelledby="protected-title">
    <span className="sessionLockIcon"><ShieldCheck size={28} /></span>
    <h1 id="protected-title">Enter your {info.label} PIN</h1>
    <p>{info.label} opens only with your own PIN for it.</p>
    {waiting
      ? <p className="formNotice formNoticeError" role="alert">Too many wrong PINs. Wait a few minutes and try again.</p>
      : <PinField length={info.pin_length} busy={busy} error={error} onPin={(pin) => send({ pin })} />}
    {owner ? <small>Forgot it? Reset it in <Link to="/admin/settings">Settings</Link> with your sign-in password.</small>
      : <small>Forgot it? Ask the business owner to reset it, then set a new one.</small>}
  </section>;
}
