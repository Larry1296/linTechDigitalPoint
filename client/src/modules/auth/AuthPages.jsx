import { usePlatform } from "../platform/PlatformContext";
import { FormField } from "../../components/forms/FormField";
import { PasswordField } from "../../components/forms/PasswordField";
import { AuthFormCard } from "./AuthFormCard";
import { FormError, FormInfo } from "../../components/forms/FormNotice";
import { Link, useLocation } from "react-router-dom";
import { useAuthForm } from "./useAuthForm";
import { useEffect, useState } from "react";
import { biometricAvailable, deviceCheck, signInsHere } from "../../core/auth/biometric";
export function LoginPage() {
  const platform = usePlatform();
  const { search } = useLocation();
  const { error, busy, submit, signInWithBiometric } = useAuthForm();
  // Both ways to sign in are on the page at once, and the person picks one: the fingerprint, face or eye check of this
  // device (where someone turned it on here) and the password. Nothing opens by itself: the device's prompt opens
  // when they tap that choice. A device that has a check but no key here says how to turn it on.
  const [people, setPeople] = useState(() => signInsHere());
  const [supported, setSupported] = useState(null);
  const [tried, setTried] = useState("password");
  useEffect(() => { void biometricAvailable().then(setSupported); }, []);
  const { name: check, Icon: CheckIcon } = deviceCheck();
  const tryBiometric = async (credentialId) => {
    setTried("biometric");
    if (!await signInWithBiometric(credentialId)) setPeople(signInsHere());
  };
  const errorHere = (where) => tried === where && <FormError title="Could not sign in." message={error} />;
  return (
    <AuthFormCard
      eyebrow={platform.name}
      title="Welcome back"
      onSubmit={(event) => { setTried("password"); return submit(event); }}
    >
      {new URLSearchParams(search).get("reason") === "session-expired" && (
        <FormInfo>Your session ended. Please sign in again.</FormInfo>
      )}
      {supported && <section className="signInChoice" aria-labelledby="sign-in-biometric">
        <h2 id="sign-in-biometric">With {check}</h2>
        {people.length ? <>
          {people.map((person) => <button type="button" key={person.credentialId} className="biometricSignIn" disabled={busy}
            onClick={() => void tryBiometric(person.credentialId)}>
            <CheckIcon size={22} aria-hidden="true" />
            {busy && tried === "biometric" ? "Signing in…" : person.username ? `Sign in as ${person.username} with ${check}` : `Sign in with ${check}`}
          </button>)}
          {errorHere("biometric")}
        </> : <p className="muted">Not on for this device yet. Sign in with your password once and you will be asked to turn it on, or turn it on in Settings.</p>}
      </section>}
      {supported && <p className="signInOr" aria-hidden="true"><span>or</span></p>}
      <section className="signInChoice" aria-labelledby="sign-in-password">
        {supported && <h2 id="sign-in-password">With your password</h2>}
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
        <button disabled={busy}>{busy && tried === "password" ? "Signing in…" : "Sign in"}</button>
        {errorHere("password")}
      </section>
      <Link to="/register">Register your business</Link>
      <Link to="/forgot-password">Forgot password?</Link>
    </AuthFormCard>
  );
}
