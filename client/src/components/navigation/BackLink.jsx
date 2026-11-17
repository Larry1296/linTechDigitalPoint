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

// Parts of an /admin address that are not pages of their own: stepping up from /admin/rooms/stays/5 skips them.
const NOT_PAGES = new Set(["/admin/rooms/stays"]);

// The page one level up in the workspace: a service's page goes to Income by service, that to the Service Desk, and
// every main page to the dashboard. The dashboard is the top and has none.
export function parentPage(pathname) {
  const path = pathname.replace(/\/+$/, "");
  if (!path.startsWith("/admin") || path === "/admin" || path === "/admin/dashboard") return null;
  let parent = path.slice(0, path.lastIndexOf("/"));
  while (NOT_PAGES.has(parent)) parent = parent.slice(0, parent.lastIndexOf("/"));
  return parent === "/admin" ? "/admin/dashboard" : parent;
}

// In the workspace, Back always goes one level up (parentPage), never to whichever page happened to be open before.
// Outside it (public and sign-in pages) it steps back through history. `to` skips both: auth pages use it, since stepping
// back from them can land on a locked /admin page, which reopens the workspace unlock overlay.
export function BackLink({ fallback, to, className = "" }) {
  const location = useLocation();
  const navigate = useNavigate();
  const up = location.pathname.startsWith("/admin") ? parentPage(location.pathname) : undefined;
  if (up === null && !to) return null;
  return <button type="button" className={`pageBackLink ${className}`} onClick={() => {
    if (to) navigate(to, { replace: true });
    else if (up) navigate(up);
    else if (canGoBack()) navigate(-1);
    else navigate(fallback || "/", { replace: true });
  }}>← Back</button>;
}
