import { BackLink } from "../../components/navigation/BackLink";
import { Link } from "react-router-dom";
import { PlatformLogo } from "../../components/Brand";
import { AuthShowcase } from "./AuthShowcase";
import { AUTH_SLIDES } from "../platform/showcase";

export function AuthFormCard({ eyebrow, title, onSubmit, children }) {
  return (
    <main className="authPage">
      <section className="authShell">
        <aside className="authIntro">
          <Link className="authIntroBrand" to="/"><PlatformLogo /></Link>
          <AuthShowcase slides={AUTH_SLIDES.login}>
            <div><span className="eyebrow">Business management, made clear</span><h2>Everything your business needs in one workspace.</h2><p>Keep products, sales, services, payments, staff, and reports connected as your business grows.</p></div>
          </AuthShowcase>
          <small>Private workspace for subscribed businesses</small>
        </aside>
        <form className="formCard" onSubmit={onSubmit}>
          <BackLink to="/" className="authBackButton" />
          <span className="eyebrow">{eyebrow}</span><h1>{title}</h1>
          {children}
        </form>
      </section>
    </main>
  );
}
