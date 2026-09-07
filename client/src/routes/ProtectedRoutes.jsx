import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { Loading } from "../components/States";
function loginTarget(path) {
  return "/login?next=" + encodeURIComponent(path);
}
export function CustomerProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!user)
    return (
      <Navigate to={loginTarget(location.pathname + location.search)} replace />
    );
  if (user.is_staff) return <Navigate to="/forbidden" replace />;
  return children;
}
export function StaffProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!user)
    return (
      <Navigate to={loginTarget(location.pathname + location.search)} replace />
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
