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
function isCustomerAccount(user) {
  return Boolean(
    user?.customer_profile ||
    user?.roles?.includes("Ecommerce Customer") ||
    !user?.is_staff,
  );
}
export function CustomerProtectedRoute({ children }) {
  const { user, loading, sessionExpired } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
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
  if (!isCustomerAccount(user)) return <Navigate to="/forbidden" replace />;
  return children;
}
export function StaffProtectedRoute({ children }) {
  const { user, loading, sessionExpired } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
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
  if (!user.is_staff) return <Navigate to="/forbidden" replace />;
  return children;
}
export function PermissionProtectedRoute({ permission, children }) {
  const { user } = useAuth();
  return user?.is_superuser || user?.permissions.includes(permission) ? (
    children
  ) : (
    <Navigate to="/forbidden" replace />
  );
}
