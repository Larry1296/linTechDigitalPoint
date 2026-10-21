import { useCallback, useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { PasswordField } from "../../components/forms/PasswordField";
import { FormError } from "../../components/forms/FormNotice";
import { Loading } from "../../components/States";

const STATUS = "/api/v1/auth/protected/";
const day = (value) => new Date(value).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

// The M-Pesa and investment pages ask for a second password of the person's own, apart from the sign-in password.
// It lasts a week, then a new one is set, never one used before. Once entered, the pages stay open on this device
// until the workspace locks or the person signs out (the server refuses these pages' records until then).
export function ProtectedPages() {
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const check = useCallback(() => api(STATUS).then((data) => setState(data.protected)).catch((err) => setError(err.message)), []);
  useEffect(() => {
    void check();
    const relock = () => void check();
    window.addEventListener("protected-locked", relock);
    window.addEventListener("session-unlocked", relock);
    return () => { window.removeEventListener("protected-locked", relock); window.removeEventListener("session-unlocked", relock); };
  }, [check]);
  if (!state) return error ? <FormError message={error} /> : <Loading />;
  if (state.unlocked) return <>
    <p className="protectedBar"><ShieldCheck size={16} aria-hidden="true" /> Protected page. Your password for these pages is due for a new one on {day(state.expires_at)}.
      <button type="button" className="linkButton" onClick={() => api("/api/v1/auth/protected/lock/", { method: "POST" }).then((data) => setState(data.protected))}>Lock now</button></p>
    <Outlet />
  </>;
  return <ProtectedPasswordForm state={state} onOpen={setState} />;
}

export function ProtectedPasswordForm({ state, onOpen }) {
  // "unlock" enters the password; "renew" replaces a week-old one; "forgot" and "first" prove it with the sign-in password.
  const [mode, setMode] = useState(!state.has_password ? "first" : state.expired ? "renew" : "unlock");
  const [form, setForm] = useState({ password: "", proof: "", next: "", again: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = (key) => ({ value: form[key], onChange: (event) => setForm({ ...form, [key]: event.target.value }), readOnly: busy, required: true });
  const switchTo = (next) => { setMode(next); setError(""); setForm({ password: "", proof: "", next: "", again: "" }); };
  async function submit(event) {
    event.preventDefault();
    if (mode !== "unlock" && form.next !== form.again) { setError("The two new passwords are not the same."); return; }
    setBusy(true); setError("");
    try {
      const data = mode === "unlock"
        ? await api("/api/v1/auth/protected/unlock/", { method: "POST", body: JSON.stringify({ password: form.password }) })
        : await api("/api/v1/auth/protected/password/", { method: "POST", body: JSON.stringify({ proof: form.proof, new_password: form.next }) });
      onOpen(data.protected);
    } catch (err) {
      if (err.data?.code === "protected_expired") { switchTo("renew"); setForm((f) => ({ ...f, proof: form.password })); }
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const titles = { first: "Set a password for protected pages", unlock: "Enter your protected pages password",
    renew: "Time for a new protected pages password", forgot: "Set a new protected pages password" };
  const notes = {
    first: `M-Pesa and investments are protected by a second password, different from the one you sign in with. It lasts ${state.lifetime_days} days; then you set a new one.`,
    unlock: "These pages are protected. Your sign-in password does not open them.",
    renew: `Your password for these pages is ${state.lifetime_days} days old. Choose a new one you have never used before.`,
    forgot: "Prove it is you with your sign-in password, then choose a new password you have never used before.",
  };
  return <section className="sessionLockCard protectedCard" aria-labelledby="protected-title">
    <span className="sessionLockIcon"><ShieldCheck size={28} /></span>
    <h1 id="protected-title">{titles[mode]}</h1>
    <p>{notes[mode]}</p>
    <form onSubmit={submit}>
      {mode === "unlock" && <PasswordField label="Protected pages password" autoComplete="off" autoFocus {...field("password")} />}
      {mode === "first" || mode === "forgot" ? <PasswordField label="Your sign-in password" autoComplete="current-password" autoFocus {...field("proof")} /> : null}
      {mode === "renew" && <PasswordField label="Your current protected pages password" autoComplete="off" autoFocus {...field("proof")} />}
      {mode !== "unlock" && <>
        <PasswordField label="New protected pages password" autoComplete="new-password" minLength={state.shortest} {...field("next")} />
        <PasswordField label="New password again" autoComplete="new-password" minLength={state.shortest} {...field("again")} />
        <small>At least {state.shortest} characters, not your sign-in password, and never one you used before.</small>
      </>}
      <button type="submit" disabled={busy}>{busy ? "Checking…" : mode === "unlock" ? "Open" : "Save and open"}</button>
      <FormError title="Could not open." message={error} />
    </form>
    {(mode === "unlock" || mode === "renew") && <button type="button" className="secondary" disabled={busy} onClick={() => switchTo("forgot")}>Forgot it? Use your sign-in password</button>}
    {mode === "forgot" && <button type="button" className="secondary" disabled={busy} onClick={() => switchTo(state.expired ? "renew" : "unlock")}>Back</button>}
  </section>;
}
