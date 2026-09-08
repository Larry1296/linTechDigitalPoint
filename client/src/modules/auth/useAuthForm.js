import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, resetCsrfToken } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useCart } from "../../core/cart/CartContext";

function safeNext(search) {
  const value = new URLSearchParams(search).get("next");
  return value &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !value.includes("\\")
    ? value
    : null;
}

export function useAuthForm({ registration = false } = {}) {
  const [error, setError] = useState("");
  const { refresh } = useAuth();
  const { refreshCart } = useCart();
  const navigate = useNavigate();
  const { search } = useLocation();
  const next = safeNext(search);
  const submit = async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (registration && data.password !== data.confirm_password) {
      setError("Passwords do not match.");
      return;
    }
    try {
      const user = await api(
        `/api/v1/auth/${registration ? "register" : "login"}/`,
        {
          method: "POST",
          body: JSON.stringify(data),
        },
      );
      resetCsrfToken();
      await Promise.all([refresh(), refreshCart()]);
      const destination =
        !registration && next?.startsWith("/admin-app") && !user.is_staff
          ? "/forbidden"
          : next ||
            (!registration && user.is_staff
              ? "/admin-app/dashboard"
              : "/account");
      navigate(destination, { replace: true });
    } catch (err) {
      setError(err.message);
    }
  };
  const accountLink = (path) =>
    path + (next ? `?next=${encodeURIComponent(next)}` : "");
  return { error, submit, accountLink };
}
