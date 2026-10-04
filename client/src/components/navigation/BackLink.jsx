import { useLocation, useNavigate } from "react-router-dom";

// BrowserRouter stores the current document's router history index. The
// referrer covers ordinary links that loaded a new document instead.
export function canGoBack() {
  if (window.history.state?.idx > 0) return true;
  if (window.history.length <= 1 || !document.referrer) return false;
  try {
    return new URL(document.referrer).origin === window.location.origin;
  } catch {
    return false;
  }
}

// `to` skips history entirely. Auth pages use it: stepping back from them can land on
// a locked /admin page, which reopens the workspace unlock overlay.
export function BackLink({ fallback, to, className = "" }) {
  const location = useLocation();
  const navigate = useNavigate();
  const destination = fallback || (location.pathname.startsWith("/admin/") && location.pathname !== "/admin/dashboard" ? "/admin/dashboard" : "/");
  return <button type="button" className={`pageBackLink ${className}`} onClick={() => {
    if (to) navigate(to, { replace: true });
    else if (canGoBack()) navigate(-1);
    else navigate(destination, { replace: true });
  }}>← Back</button>;
}
