import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, resetCsrfToken } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { rememberPasswordLength } from "../../core/auth/passwordLength";
import { biometricAvailable, cancelled, deviceCheck, deviceLabel, keyHere, makeKey, rememberKey, signInWithKey } from "../../core/auth/biometric";
import { confirmAction } from "../../core/ui/alerts";

function safeNext(search) {
  const value = new URLSearchParams(search).get("next");
  return value &&
    value.startsWith("/admin/") &&
    !value.startsWith("//") &&
    !value.includes("\\")
    ? value
    : null;
}

// Signed in with the password on a device that has a fingerprint, face or eye check but no key here yet: offer to
// turn it on now, with the password just typed, so the next sign-in is a touch of the sensor. A "no", a closed prompt
// or any problem simply goes on to the workspace; Settings can turn it on later.
async function offerBiometric(identity, password) {
  try {
    if (identity.setup_required || !identity.id || keyHere(identity.id) || !await biometricAvailable()) return;
    const { name } = deviceCheck();
    if (!await confirmAction({ title: `Use ${name} next time?`, icon: "question", confirmButtonText: "Yes, turn it on",
      text: `Sign in and unlock on this device with ${name} instead of typing your password. Your password and PIN still work.` })) return;
    const { options } = await api("/api/v1/auth/biometric/start/", { method: "POST", body: JSON.stringify({ password }) });
    const credential = await makeKey(options);
    const key = await api("/api/v1/auth/biometric/finish/", { method: "POST",
      body: JSON.stringify({ credential, label: deviceLabel(), windows_hello: name === "Windows Hello" }) });
    rememberKey(identity.id, key.credential_id, identity.username);
  } catch { /* Not now: it can be turned on in Settings. */ }
}

export function useAuthForm() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { signedIn } = useAuth();
  const navigate = useNavigate();
  const { search } = useLocation();
  const next = safeNext(search);
  const arrive = async (identity) => {
    resetCsrfToken();
    await signedIn();
    const destination = identity.organization ? next || "/admin/dashboard" : identity.memberships?.length ? "/select-business" : "/onboarding";
    navigate(destination, { replace: true });
  };
  // Signing in with the fingerprint or face this browser has on; closing the device's prompt is not an error.
  // Returns false when the password is needed instead.
  const signInWithBiometric = async (credentialId) => {
    if (busy) return true;
    setError("");
    setBusy(true);
    try {
      await arrive(await signInWithKey(api, credentialId));
      return true;
    } catch (err) {
      if (!cancelled(err)) setError(err.data?.code ? err.message : `This device could not check your ${deviceCheck().name}. Try again, or use your password.`);
      return err.data?.code !== "biometric_unknown";
    } finally {
      setBusy(false);
    }
  };
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    const data = Object.fromEntries(new FormData(event.currentTarget));
    // Clear the last attempt's error so a corrected retry starts fresh, and the same mistake made again shows again.
    setError("");
    setBusy(true);
    try {
      const identity = await api(
        "/api/v1/auth/login/",
        {
          method: "POST",
          body: JSON.stringify(data),
        },
      );
      rememberPasswordLength(data.password);
      await offerBiometric(identity, data.password);
      await arrive(identity);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, submit, signInWithBiometric, setError };
}
