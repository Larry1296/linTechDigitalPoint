import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { Loading } from "../components/States";
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
  if (!user.organization) return <Navigate to={user.memberships?.length ? "/select-business" : "/onboarding"} replace />;
  const area = location.pathname.split("/")[2];
  const modules = {pos:"pos", products:"inventory", "product-lookup":"inventory", receive:"inventory", "quick-receive":"inventory", "opening-stock":"inventory", receipts:"inventory", "adjust-stock":"inventory", categories:"inventory", brands:"inventory", "shelf-management":"locations", cyber:"services", mpesa:"mpesa", reports:"reports", analytics:"reports"};
  if (modules[area] && !user.organization.enabled_modules.includes(modules[area])) return <p role="alert">This module is not enabled for your business.</p>;
  return children;
}
export function PermissionProtectedRoute({ permission, children }) {
  const { user } = useAuth();
  return user?.permissions.includes(permission) ? (
    children
  ) : (
    <Navigate to="/forbidden" replace />
  );
}
