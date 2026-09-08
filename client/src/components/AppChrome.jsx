import { Bell, Menu, ShoppingCart, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { useCart } from "../core/cart/CartContext";
import { ThemePicker } from "./ThemePicker";
import { useSignOut } from "../core/auth/useSignOut";
import logoUrl from "../assets/images/logo.png";
function can(permission, user) {
  return Boolean(user?.is_superuser || user?.permissions.includes(permission));
}
function displayRole(user) {
  if (user.is_superuser) return "Admin";
  if (user.is_staff) return user.roles.join(", ") || "Staff";
  return "Customer";
}
export function BrandLogo({ compact = false }) {
  return (
    <img
      className={`brandLogo${compact ? " compact" : ""}`}
      src={logoUrl}
      alt="LinTech Digital Point"
    />
  );
}
export function AppNavbar({ accountMenu, accountMenuRef } = {}) {
  const { user } = useAuth();
  const { count } = useCart();
  const location = useLocation();
  const isStaffDashboard = location.pathname.startsWith("/admin-app");
  const isCustomerDashboard =
    location.pathname === "/account" ||
    location.pathname.startsWith("/account/");
  const isDashboard = isStaffDashboard || isCustomerDashboard;
  const dashboardTitle = isCustomerDashboard ? "My Account" : "Dashboard";
  const isAuthPage = ["/login", "/register"].includes(location.pathname);
  const [openLocation, setOpenLocation] = useState(null);
  const mobileMenuOpen = openLocation === location.key;
  const navbarRef = useRef(null);
  const mobileToggleRef = useRef(null);
  useEffect(() => {
    if (!mobileMenuOpen) return;
    const closeOutside = (event) => {
      if (!navbarRef.current?.contains(event.target)) setOpenLocation(null);
    };
    const desktop = window.matchMedia("(min-width: 761px)");
    const closeOnDesktop = () => {
      if (desktop.matches) setOpenLocation(null);
    };
    document.addEventListener("pointerdown", closeOutside);
    desktop.addEventListener("change", closeOnDesktop);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      desktop.removeEventListener("change", closeOnDesktop);
    };
  }, [mobileMenuOpen]);
  const signOut = useSignOut();
  return (
    <header
      ref={navbarRef}
      onKeyDown={(event) => {
        if (event.key === "Escape" && mobileMenuOpen) {
          setOpenLocation(null);
          mobileToggleRef.current?.focus();
        }
      }}
      className={`appNavbar${isDashboard ? " dashboardNavbar" : ""}${isAuthPage ? " authNavbar" : ""}${accountMenu ? " customerDashboardNavbar" : ""}${mobileMenuOpen ? " mobileMenuOpen" : ""}`}
    >
      <Link
        className="brand"
        to={user?.is_staff ? "/admin-app/dashboard" : "/"}
      >
        <BrandLogo />
      </Link>
      {isDashboard && <div className="dashboardTitle">{dashboardTitle}</div>}
      {accountMenu && (
        <button
          ref={accountMenuRef}
          className="customerSidebarToggle"
          type="button"
          aria-label={
            accountMenu.open ? "Close account menu" : "Open account menu"
          }
          aria-controls="customer-sidebar"
          aria-expanded={accountMenu.open}
          onClick={accountMenu.toggle}
        >
          {accountMenu.open ? (
            <X size={24} aria-hidden="true" />
          ) : (
            <Menu size={24} aria-hidden="true" />
          )}
        </button>
      )}
      {!isDashboard && (
        <button
          ref={mobileToggleRef}
          className="mobileMenuButton"
          type="button"
          aria-label={
            mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"
          }
          aria-controls="public-navigation public-account-actions"
          aria-expanded={mobileMenuOpen}
          onClick={() => setOpenLocation(mobileMenuOpen ? null : location.key)}
        >
          {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      )}
      {!isDashboard && (
        <nav
          id="public-navigation"
          className={mobileMenuOpen ? "mobileMenuOpen" : undefined}
          aria-label="Main navigation"
          onClick={() => setOpenLocation(null)}
        >
          <NavLink to="/">Home</NavLink>
          <NavLink to="/shop">Shop</NavLink>
          <Link to="/#categories">Categories</Link>
          <Link to="/#services">Services</Link>
        </nav>
      )}
      {!accountMenu?.mobile && (
        <div
          id={!isDashboard ? "public-account-actions" : undefined}
          className={`navActions${mobileMenuOpen ? " mobileMenuOpen" : ""}`}
          onClick={(event) => {
            if (event.target.closest("a")) setOpenLocation(null);
          }}
        >
          {isStaffDashboard && (
            <div className="dashboardNotification" title="Live notifications">
              <Bell size={21} aria-hidden="true" />
              <span className="liveDot" aria-hidden="true" />
              <span className="sr">Live notifications</span>
            </div>
          )}
          {!isDashboard && (
            <NavLink to="/cart">
              <ShoppingCart size={18} /> Cart{" "}
              <span className="cartBadge">{count}</span>
            </NavLink>
          )}
          <ThemePicker />
          {!isDashboard && (
            <>
              {user?.is_staff ? (
                <NavLink className="staffPortalLink" to="/admin-app/dashboard">
                  Admin
                </NavLink>
              ) : user ? (
                <>
                  <NavLink to="/account">My Account</NavLink>
                  <NavLink to="/account/orders">Orders</NavLink>
                </>
              ) : (
                <NavLink className="authEntryLink" to="/login">
                  Login/Register
                </NavLink>
              )}
            </>
          )}
          {isDashboard && (
            <div className="dashboardMobileTitle">{dashboardTitle}</div>
          )}
          {user && (
            <div className="navIdentity">
              <span className="navUserName">
                {user.first_name || user.username} ({displayRole(user)})
              </span>
              <button
                className="linkButton logoutLink"
                onClick={() => void signOut()}
              >
                Logout
              </button>
            </div>
          )}
        </div>
      )}
    </header>
  );
}
export function AppFooter() {
  const { user } = useAuth();
  return (
    <footer className="appFooter">
      <div>
        <Link className="brand" to="/">
          <BrandLogo compact />
        </Link>
        <p>
          {user?.is_staff
            ? "Secure operations for LinTech Digital Point."
            : "Technology, accessories and everyday services you can count on."}
        </p>
      </div>
      <div>
        <b>{user?.is_staff ? "Operations" : "Quick links"}</b>
        {user?.is_staff ? (
          <>
            <Link to="/admin-app/dashboard">Dashboard</Link>
            {can("commerce.add_sale", user) && (
              <Link to="/admin-app/pos">Point of Sale</Link>
            )}
            {can("inventory.view_shelf", user) && (
              <Link to="/admin-app/digital-shop">Digital Shop</Link>
            )}
          </>
        ) : (
          <>
            <Link to="/shop">Shop</Link>
            <Link to="/cart">Cart</Link>
            {user && <Link to="/account">My Account</Link>}
          </>
        )}
      </div>
      <div>
        <b>{user?.is_staff ? "Account" : "Customer help"}</b>
        {user?.is_staff ? (
          <>
            <span>Signed in as {user.first_name || user.username}</span>
            <span>
              {user.is_superuser
                ? "Owner / Administrator"
                : user.roles.join(", ") || "Staff"}
            </span>
          </>
        ) : (
          <>
            <Link to="/#contact">Contact us</Link>
            <span>
              Pickup and delivery information is provided at checkout.
            </span>
          </>
        )}
      </div>
    </footer>
  );
}
