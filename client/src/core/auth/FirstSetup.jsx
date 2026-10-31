import { useState } from "react";
import { KeyRound } from "lucide-react";
import { api } from "../api/client";
import { PasswordField } from "../../components/forms/PasswordField";
import { FormError } from "../../components/forms/FormNotice";
import { useAuth } from "./AuthContext";

// A new account's first sign-in (or one the owner reset): before anything opens, the person replaces the temporary
// password the business owner gave them with their own and chooses their lock PIN. Nobody else knows either.
export function FirstSetup() {
  const { user, refresh, logout } = useAuth();
  const [form, setForm] = useState({ password: "", again: "", pin: "", pinAgain: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pinKeys = ["pin", "pinAgain"];
  const field = (key) => ({ value: form[key], readOnly: busy, required: true,
    onChange: (event) => setForm({ ...form, [key]: pinKeys.includes(key) ? event.target.value.replace(/\D/g, "").slice(0, 6) : event.target.value }) });
  const save = async (event) => {
    event.preventDefault();
    if (form.password !== form.again) { setError("The two passwords are not the same."); return; }
    if (!/^\d{4,6}$/.test(form.pin)) { setError("A PIN is 4 to 6 numbers (0 to 9), with no letters."); return; }
    if (form.pin !== form.pinAgain) { setError("The two PINs are not the same."); return; }
    setBusy(true); setError("");
    try {
      await api("/api/v1/auth/setup/", { method: "POST", body: JSON.stringify({ new_password: form.password, pin: form.pin }) });
      await refresh();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return <div className="sessionLockBackdrop firstSetup">
    <section className="sessionLockCard" aria-labelledby="setup-title">
      <span className="sessionLockIcon"><KeyRound size={28} /></span>
      <span className="eyebrow">{user?.organization?.name}</span>
      <h1 id="setup-title">Welcome{user?.first_name ? `, ${user.first_name}` : ""}. Set up your sign-in</h1>
      <p>The business owner gave you a temporary password. Choose your own now, and a lock PIN that opens your workspace after you lock it.
        Keep both to yourself: nobody else, not even the owner, will know them.</p>
      <form onSubmit={(event) => void save(event)}>
        <PasswordField label="Your new password" autoComplete="new-password" minLength={8} autoFocus {...field("password")} />
        <PasswordField label="Your new password again" autoComplete="new-password" minLength={8} {...field("again")} />
        <PasswordField label="Your lock PIN (4 to 6 numbers)" inputMode="numeric" autoComplete="off" maxLength={6} {...field("pin")} />
        <PasswordField label="Your lock PIN again" inputMode="numeric" autoComplete="off" maxLength={6} {...field("pinAgain")} />
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save and continue"}</button>
        <FormError title="Could not save." message={error} />
      </form>
      <small><button type="button" className="linkButton" onClick={() => void logout()}>Sign out</button></small>
    </section>
  </div>;
}
