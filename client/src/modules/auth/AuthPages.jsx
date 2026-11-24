import { usePlatform } from "../platform/PlatformContext";
import { FormField } from "../../components/forms/FormField";
import { PasswordField } from "../../components/forms/PasswordField";
import { AuthFormCard } from "./AuthFormCard";
import { FormError, FormInfo } from "../../components/forms/FormNotice";
import { Link, useLocation } from "react-router-dom";
import { useAuthForm } from "./useAuthForm";
import { useEffect, useState } from "react";
import { Fingerprint } from "lucide-react";
import { biometricAvailable, signInsHere } from "../../core/auth/biometric";
export function LoginPage() {
  const platform = usePlatform();
  const { search } = useLocation();
  const { error, busy, submit, signInWithBiometric } = useAuthForm();
  // Where someone turned on fingerprint or face sign-in on this device, it is the first choice; the password is the other.
  const [people, setPeople] = useState(() => signInsHere());
  const [supported, setSupported] = useState(true);
  const [byPassword, setByPassword] = useState(false);
  useEffect(() => { void biometricAvailable().then(setSupported); }, []);
  const byBiometric = people.length > 0 && supported && !byPassword;
  const tryBiometric = async (credentialId) => {
    if (!await signInWithBiometric(credentialId)) {
      const left = signInsHere();
      setPeople(left);
      if (!left.length) setByPassword(true);
    }
  };
  return (
    <AuthFormCard
      eyebrow={platform.name}
      title="Welcome back"
      onSubmit={submit}
    >
      {new URLSearchParams(search).get("reason") === "session-expired" && (
        <FormInfo>Your session ended. Please sign in again.</FormInfo>
      )}
      {byBiometric ? <>
        {people.map((person) => <button type="button" key={person.credentialId} className="biometricSignIn" disabled={busy}
          onClick={() => void tryBiometric(person.credentialId)}>
          <Fingerprint size={22} aria-hidden="true" />
          {busy ? "Signing in…" : person.username ? `Sign in as ${person.username} with fingerprint or face` : "Sign in with fingerprint or face"}
        </button>)}
        <FormError title="Could not sign in." message={error} />
        <button type="button" className="linkButton" disabled={busy} onClick={() => setByPassword(true)}>Use your password instead</button>
      </> : <>
        <FormField
          label="Username or email"
          name="credential"
          required
          autoComplete="username"
        />
        <PasswordField
          label="Password"
          name="password"
          required
          autoComplete="current-password"
        />
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <FormError title="Could not sign in." message={error} />
        {people.length > 0 && supported && <button type="button" className="linkButton" disabled={busy} onClick={() => setByPassword(false)}>Use fingerprint or face instead</button>}
      </>}
      <Link to="/register">Register your business</Link>
      <Link to="/forgot-password">Forgot password?</Link>
    </AuthFormCard>
  );
}
