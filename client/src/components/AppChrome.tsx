import { Bell, Menu, ShoppingCart, X } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { useCart } from "../core/cart/CartContext";
import { ThemePicker } from "./ThemePicker";
import logoUrl from "../assets/images/logo.png";

function can(permission: string, user: ReturnType<typeof useAuth>["user"]) {
  return Boolean(user?.is_superuser || user?.permissions.includes(permission));
}

function displayRole(user: NonNullable<ReturnType<typeof useAuth>["user"]>) {
  if (user.is_superuser) return "Admin";
  if (user.is_staff) return user.roles.join(", ") || "Staff";
  return "Customer";
}

export function BrandLogo({ compact = false }: { compact?: boolean }) {
  return (
    <img
      className={`brandLogo${compact ? " compact" : ""}`}
      src={logoUrl}
      alt="LinTech Digital Point"
    />
  );
}

export function AppNavbar() {
  const { user, logout } = useAuth();
  const { count, refreshCart } = useCart();
  const location = useLocation();
  const isDashboard = location.pathname.startsWith("/admin-app");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const signOut = async () => {
    await logout();
    await refreshCart();
  };
  return (
    <header className={`appNavbar${isDashboard ? " dashboardNavbar" : ""}`}>
      <Link
        className="brand"
        to={user?.is_staff ? "/admin-app/dashboard" : "/"}
      >
        <BrandLogo />
      </Link>
      {isDashboard && <div className="dashboardTitle">Dashboard</div>}
      {!isDashboard && (
        <button
          className="mobileMenuButton"
          type="button"
          aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
          aria-expanded={mobileMenuOpen}
          onClick={() => setMobileMenuOpen((open) => !open)}
        >
          {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      )}
      {!isDashboard && (
        <nav
          className={mobileMenuOpen ? "mobileMenuOpen" : undefined}
          aria-label="Main navigation"
        >
          <NavLink to="/">Home</NavLink>
          <NavLink to="/shop">Shop</NavLink>
          <Link to="/#categories">Categories</Link>
          <Link to="/#services">Services</Link>
          <NavLink to="/cart">
            <ShoppingCart size={18} /> Cart{" "}
            <span className="cartBadge">{count}</span>
          </NavLink>
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
        </nav>
      )}
      <div className="navActions">
        {isDashboard && (
          <div className="dashboardNotification" title="Live notifications">
            <Bell size={21} aria-hidden="true" />
            <span className="liveDot" aria-hidden="true" />
            <span className="sr">Live notifications</span>
          </div>
        )}
        <ThemePicker />
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
