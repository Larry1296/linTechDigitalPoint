import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { Loading } from "../components/States";
import { FirstSetup } from "../core/auth/FirstSetup";
function loginTarget(path, expired) {
  return (
    "/login?" +
    (expired ? "reason=session-expired&" : "") +
    "next=" +
    encodeURIComponent(path)
  );
}
export function StaffProtectedRoute({ children }) {
  const { user, loading, sessionExpired, locked } = useAuth();
  const location = useLocation();
  if (loading || (locked && !user?.organization)) return <Loading />;
  if (!user)
    return (
      <Navigate
        to={loginTarget(
          location.pathname + location.search + location.hash,
          sessionExpired,
        )}
        replace
      />
    );
  if (!user.organization && !user.memberships?.length && user.switched_off_businesses?.length) return <SwitchedOff names={user.switched_off_businesses} />;
  if (!user.organization) return <Navigate to={user.memberships?.length ? "/select-business" : "/onboarding"} replace />;
  // A new employee (or one the owner reset) chooses their own password and lock PIN before anything opens.
  if (user.setup_required) return <FirstSetup />;
  const area = location.pathname.split("/")[2];
  const modules = {pos:"pos", products:"inventory", "product-lookup":"inventory", receive:"inventory", "quick-receive":"inventory", "opening-stock":"inventory", receipts:"inventory", "adjust-stock":"inventory", categories:"inventory", brands:"inventory", "shelf-management":"locations", cyber:"services", mpesa:"mpesa", investments:"investments", reports:"reports", analytics:"reports"};
  if (modules[area] && !user.organization.enabled_modules.includes(modules[area])) return <p role="alert">This module is not enabled for your business.</p>;
  return children;
}
// The platform switched the person's business off: say so, instead of offering to set up a new business.
function SwitchedOff({ names }) {
  return <section className="state" role="alert">
    <h1>{names.join(", ")} is switched off</h1>
    <p>The platform has switched this business off, so it cannot be opened for now. Nothing has been deleted.</p>
    <p>Contact linTech support to have it switched back on.</p>
  </section>;
}
export function PermissionProtectedRoute({ permission, children }) {
  const { user } = useAuth();
  return user?.permissions.includes(permission) ? (
    children
  ) : (
    <Navigate to="/forbidden" replace />
  );
}
