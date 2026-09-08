import { FormField } from "../../components/forms/FormField";
import { PasswordField } from "../../components/forms/PasswordField";
import { AuthFormCard } from "./AuthFormCard";
import { Link } from "react-router-dom";
import { useAuthForm } from "./useAuthForm";
export function LoginPage() {
  const { error, submit, accountLink } = useAuthForm();
  return (
    <AuthFormCard
      eyebrow="LinTech Digital Point"
      title="Welcome back"
      error={error}
      onSubmit={submit}
    >
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
      <Link to="/password-reset">Forgot password?</Link>
      <hr />
      <span>New customer?</span>
      <Link className="button secondary" to={accountLink("/register")}>
        Create account
      </Link>
    </AuthFormCard>
  );
}
export function RegisterPage() {
  const { error, submit, accountLink } = useAuthForm({ registration: true });
  return (
    <AuthFormCard
      eyebrow="LinTech customer"
      title="Create account"
      error={error}
      onSubmit={submit}
    >
      <FormField
        label="Full name"
        name="first_name"
        required
        autoComplete="name"
      />
      <FormField
        label="Username"
        name="username"
        required
        autoComplete="username"
      />
      <FormField
        label="Email"
        name="email"
        type="email"
        required
        autoComplete="email"
      />
      <FormField label="Phone" name="phone" autoComplete="tel" />
      <PasswordField
        label="Password"
        name="password"
        minLength={8}
        required
        autoComplete="new-password"
      />
      <PasswordField
        label="Confirm password"
        name="confirm_password"
        minLength={8}
        required
        autoComplete="new-password"
      />
      <button>Register</button>
      <span>Already registered?</span>
      <Link to={accountLink("/login")}>Sign in</Link>
    </AuthFormCard>
  );
}
