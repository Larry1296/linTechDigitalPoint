import { BackLink } from "../../components/navigation/BackLink";
import { AuthShowcase } from "../auth/AuthShowcase";
import { AUTH_SLIDES } from "./showcase";
import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../../core/auth/AuthContext";
import { api, resetCsrfToken } from "../../core/api/client";
import { Loading } from "../../components/States";
import { usePlatform } from "./PlatformContext";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { PasswordField } from "../../components/forms/PasswordField";
import { TextBox } from "../../components/forms/TextBox";
export function RegisterPage() {
  const platform = usePlatform();
  const { signedIn } = useAuth();
  const navigate = useNavigate();
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (values.password !== values.password_confirm) { setError("The two passwords do not match."); return; }
    setBusy(true);
    try {
      await api("/api/v1/tenancy/register/", {method:"POST",body:JSON.stringify(values)});
      resetCsrfToken(); await signedIn(); navigate("/onboarding");
    } catch(error) { setError(error.message); } finally { setBusy(false); }
  }
  return <main className="tenantForm authStandalone"><div className="authStandaloneIntro"><AuthShowcase slides={AUTH_SLIDES.register}><div><span className="eyebrow">Business management, made clear</span><h2>Everything your business needs in one workspace.</h2><p>Set up a private workspace for your business and keep daily operations connected.</p></div></AuthShowcase></div>
  <div className="authStandaloneForm"><BackLink to="/" className="authBackButton" /><Link to="/">{platform.name}</Link><h1>Create your account</h1>
    <p>Step 1 of 2: your personal details. Next, you will set up your business.</p>
    <form onSubmit={submit} className="registerForm">
      <fieldset>
        <legend>About you</legend>
        <div className="registerRow">
          <label>First name<TextBox name="first_name" autoComplete="given-name" required maxLength={150} /></label>
          <label>Last name<TextBox name="last_name" autoComplete="family-name" required maxLength={150} /></label>
        </div>
        <label>Phone number<input name="phone" type="tel" inputMode="tel" autoComplete="tel" required maxLength={20} placeholder="0712 345 678" /></label>
        <label>Email<input name="email" type="email" autoComplete="email" required placeholder="you@example.com" aria-describedby="register-email-hint" /></label>
        <small id="register-email-hint">Used for password resets and receipts you send.</small>
      </fieldset>
      <fieldset>
        <legend>Sign-in details</legend>
        <label>Username<TextBox name="username" autoComplete="username" required maxLength={150} pattern="[\w.@+\-]+" title="Letters, numbers and . @ + - _ only, no spaces" aria-describedby="register-username-hint" /></label>
        <small id="register-username-hint">You sign in with this or your email. No spaces.</small>
        <div className="registerRow">
          <PasswordField label="Password" name="password" autoComplete="new-password" minLength={8} required />
          <PasswordField label="Confirm password" name="password_confirm" autoComplete="new-password" minLength={8} required />
        </div>
        <small className="muted">At least 8 characters. Avoid common words and passwords that look like your name.</small>
      </fieldset>
      <button disabled={busy}>{busy?"Creating account…":"Create account and continue"}</button><FormError title="Could not create your account." message={error} /><Link to="/login">Already have an account? Sign in</Link>
    </form></div></main>;
}
// The business set-up is a guided, step-by-step flow.
export { BusinessSetupPage as OnboardingPage } from "./BusinessSetup";
export async function switchBusiness(id) {
  await api("/api/v1/tenancy/select/", {method:"POST",body:JSON.stringify({organization_id:Number(id)})});
  // A document reload discards all old-tenant component state and pending UI work.
  window.location.assign("/admin/dashboard");
}

export async function switchBranch(id) {
  return api("/api/v1/tenancy/select-branch/", {method:"POST", body:JSON.stringify({branch_id:Number(id)})});
}
export function SelectBusinessPage() {
  const {user,loading} = useAuth(); const [error,setError] = useState("");
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  return <main className="tenantForm"><BackLink className="authBackButton" /><h1>Select a business</h1>{error && <p role="alert">{error}</p>}{user.memberships?.map(({organization,role}) => <p key={organization.id}><button onClick={() => switchBusiness(organization.id).catch(error=>setError(error.message))}>{organization.name} · {role}</button></p>)}<Link to="/onboarding">Create another business</Link></main>;
}
export function ForgotPasswordPage() {
  const [message,setMessage] = useState("");
  const [error,setError] = useState("");
  async function submit(event) { event.preventDefault(); setMessage(""); setError(""); try { const result = await api("/api/v1/auth/password/reset/",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))}); setMessage(result.detail); } catch(error) { setError(error.message); } }
  return <main className="tenantForm authStandalone"><div className="authStandaloneIntro"><AuthShowcase slides={AUTH_SLIDES.forgotPassword}><div><span className="eyebrow">Secure account access</span><h2>Get back to your business workspace.</h2><p>Request a reset link and continue managing your business securely.</p></div></AuthShowcase></div><div className="authStandaloneForm"><BackLink to="/" className="authBackButton" /><h1>Reset your password</h1><form onSubmit={submit}><label>Email<input name="email" type="email" required autoComplete="email" /></label><button>Request reset instructions</button><FormSuccess message={message} /><FormError title="Could not send reset instructions." message={error} /><Link to="/login">Back to login</Link></form></div></main>;
}

export function ResetPasswordPage() {
  const [message,setMessage] = useState("");
  const [error,setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    const query = new URLSearchParams(window.location.search);
    const data = {...Object.fromEntries(new FormData(event.currentTarget)),uid:query.get("uid"),token:query.get("token")};
    setMessage(""); setError("");
    try { const result = await api("/api/v1/auth/password/reset/confirm/",{method:"POST",body:JSON.stringify(data)}); setMessage(result.detail); }
    catch(error) { setError(error.message); }
  }
  return <main className="tenantForm authStandalone"><div className="authStandaloneIntro"><AuthShowcase slides={AUTH_SLIDES.resetPassword}><div><span className="eyebrow">Secure account access</span><h2>Choose a password you can trust.</h2><p>Your account gives you access to the private workspace for your business.</p></div></AuthShowcase></div><div className="authStandaloneForm"><BackLink to="/" className="authBackButton" /><h1>Choose a new password</h1><form onSubmit={submit}><label>New password<input name="password" type="password" autoComplete="new-password" minLength={8} required /></label><button>Reset password</button><FormSuccess message={message} /><FormError title="Could not reset your password." message={error} /><Link to="/login">Back to login</Link></form></div></main>;
}
