import { Link } from "react-router-dom";

export function AuthFormCard({ eyebrow, title, error, onSubmit, children }) {
  return (
    <main className="authPage">
      <form className="formCard" onSubmit={onSubmit}>
        <Link className="authBackButton" to="/">
          ← Back
        </Link>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {error && <p className="formError">{error}</p>}
        {children}
      </form>
    </main>
  );
}
