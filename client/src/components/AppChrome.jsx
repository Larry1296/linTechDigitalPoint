import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { PublicNavbar, PublicFooter } from "../modules/platform/PublicSite";
import { BusinessBrand, PlatformLogo } from "./Brand";
export function BrandLogo({ compact = false }) {
  const {user} = useAuth(); const location = useLocation();
  const business = location.pathname.startsWith('/admin') ? user?.organization : null;
  return business ? <BusinessBrand organization={business} compact={compact} /> : <PlatformLogo compact={compact} />;
}
export function AppNavbar() { return <PublicNavbar />; }
export function AppFooter() {
  const {user} = useAuth();
  if (!user?.organization) return <PublicFooter />;
  return <footer className="appFooter"><div><BusinessBrand organization={user.organization} /><span className="poweredBy">Powered by <PlatformLogo compact /></span></div><div><Link to="/admin/dashboard">Dashboard</Link><Link to="/admin/subscription">Subscription</Link><Link to="/">Public website</Link></div><div>Signed in as {user.first_name || user.username}</div></footer>;
}
