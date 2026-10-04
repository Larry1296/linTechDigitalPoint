import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, resetCsrfToken } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";

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
  const { signedIn } = useAuth();
  const navigate = useNavigate();
  const { search } = useLocation();
  const next = safeNext(search);
  const submit = async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const identity = await api(
        "/api/v1/auth/login/",
        {
          method: "POST",
          body: JSON.stringify(data),
        },
      );
      resetCsrfToken();
      await signedIn();
      const destination = identity.organization ? next || "/admin/dashboard" : identity.memberships?.length ? "/select-business" : "/onboarding";
      navigate(destination, { replace: true });
    } catch (err) {
      setError(err.message);
    }
  };
  return { error, submit };
}
