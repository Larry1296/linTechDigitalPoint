import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, resetCsrfToken } from "../../core/api/client";
import { useAuth } from "../../core/auth/AuthContext";
import { useCart } from "../../core/cart/CartContext";
import type { Identity } from "../../types";
function safeNext(search: string) {
  const value = new URLSearchParams(search).get("next");
  return value &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !value.includes("\\")
    ? value
    : null;
}
export function LoginPage() {
  const [error, setError] = useState("");
  const { refresh } = useAuth();
  const { refreshCart } = useCart();
  const nav = useNavigate();
  const location = useLocation();
  const next = safeNext(location.search);
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    try {
      const user = await api<Identity>("/api/v1/auth/login/", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      resetCsrfToken();
      await Promise.all([refresh(), refreshCart()]);
      if (next?.startsWith("/admin-app") && !user.is_staff)
        nav("/forbidden", { replace: true });
      else
        nav(next || (user.is_staff ? "/admin-app/dashboard" : "/account"), {
          replace: true,
        });
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <main className="authPage">
      <form className="formCard" onSubmit={submit}>
        <Link className="authBackButton" to="/">
          ← Back
        </Link>
        <span className="eyebrow">LinTech Digital Point</span>
        <h1>Welcome back</h1>
        {error && <p className="formError">{error}</p>}
        <label>
          Username or email
          <input name="credential" required autoComplete="username" />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            required
            autoComplete="current-password"
          />
        </label>
        <button>Sign in</button>
        <Link to="/password-reset">Forgot password?</Link>
        <hr />
        <span>New customer?</span>
        <Link
          className="button secondary"
          to={"/register" + (next ? "?next=" + encodeURIComponent(next) : "")}
        >
          Create account
        </Link>
      </form>
    </main>
  );
}
export function RegisterPage() {
  const [error, setError] = useState("");
  const { refresh } = useAuth();
  const { refreshCart } = useCart();
  const nav = useNavigate();
  const location = useLocation();
  const next = safeNext(location.search);
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.currentTarget));
    if (data.password !== data.confirm_password) {
      setError("Passwords do not match.");
      return;
    }
    try {
      await api("/api/v1/auth/register/", {
        method: "POST",
        body: JSON.stringify(data),
      });
      resetCsrfToken();
      await Promise.all([refresh(), refreshCart()]);
      nav(next || "/account", { replace: true });
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <main className="authPage">
      <form className="formCard" onSubmit={submit}>
        <Link className="authBackButton" to="/">
          ← Back
        </Link>
        <span className="eyebrow">LinTech customer</span>
        <h1>Create account</h1>
        {error && <p className="formError">{error}</p>}
        <label>
          Full name
          <input name="first_name" required autoComplete="name" />
        </label>
        <label>
          Username
          <input name="username" required autoComplete="username" />
        </label>
        <label>
          Email
          <input name="email" type="email" required autoComplete="email" />
        </label>
        <label>
          Phone
          <input name="phone" autoComplete="tel" />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            minLength={8}
            required
            autoComplete="new-password"
          />
        </label>
        <label>
          Confirm password
          <input
            name="confirm_password"
            type="password"
            minLength={8}
            required
            autoComplete="new-password"
          />
        </label>
        <button>Register</button>
        <span>Already registered?</span>
        <Link to={"/login" + (next ? "?next=" + encodeURIComponent(next) : "")}>
          Sign in
        </Link>
      </form>
    </main>
  );
}
