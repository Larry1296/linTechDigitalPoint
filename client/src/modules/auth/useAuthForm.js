import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, resetCsrfToken } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { rememberPasswordLength } from "../../core/auth/passwordLength";
import { cancelled, deviceCheck, signInWithKey } from "../../core/auth/biometric";

function safeNext(search) {
  const value = new URLSearchParams(search).get("next");
  return value &&
    value.startsWith("/admin/") &&
    !value.startsWith("//") &&
    !value.includes("\\")
    ? value
    : null;
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
      await arrive(identity);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, submit, signInWithBiometric, setError };
}
