import { usePlatform } from "../platform/PlatformContext";
import { FormField } from "../../components/forms/FormField";
import { PasswordField } from "../../components/forms/PasswordField";
import { AuthFormCard } from "./AuthFormCard";
import { FormError, FormInfo } from "../../components/forms/FormNotice";
import { Link, useLocation } from "react-router-dom";
import { useAuthForm } from "./useAuthForm";
export function LoginPage() {
  const platform = usePlatform();
  const { search } = useLocation();
  const { error, submit } = useAuthForm();
  return (
    <AuthFormCard
      eyebrow={platform.name}
      title="Welcome back"
      onSubmit={submit}
    >
      {new URLSearchParams(search).get("reason") === "session-expired" && (
        <FormInfo>Your session ended. Please sign in again.</FormInfo>
      )}
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
      <button>Sign in</button>
      <FormError title="Could not sign in." message={error} />
      <Link to="/register">Register your business</Link>
      <Link to="/forgot-password">Forgot password?</Link>
    </AuthFormCard>
  );
}
