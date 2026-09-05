import { ShoppingCart } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { useCart } from "../core/cart/CartContext";
import { ThemePicker } from "./ThemePicker";
import logoUrl from "../assets/images/logo.png";

function can(permission: string, user: ReturnType<typeof useAuth>["user"]) {
  return Boolean(user?.is_superuser || user?.permissions.includes(permission));
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
  const signOut = async () => {
    await logout();
    await refreshCart();
  };
  return (
    <header className="appNavbar">
      <Link
        className="brand"
        to={user?.is_staff ? "/admin-app/dashboard" : "/"}
      >
        <BrandLogo />
      </Link>
      <nav aria-label="Main navigation">
        <NavLink to="/">Home</NavLink>
        <NavLink to="/shop">Shop</NavLink>
        <Link to="/#categories">Categories</Link>
        <Link to="/#services">Services</Link>
        <NavLink to="/cart">
          <ShoppingCart size={18} /> Cart{" "}
          <span className="cartBadge">{count}</span>
        </NavLink>
        {user?.is_staff ? (
          <NavLink to="/admin-app/dashboard">Admin</NavLink>
        ) : user ? (
          <>
            <NavLink to="/account">My Account</NavLink>
            <NavLink to="/account/orders">Orders</NavLink>
          </>
        ) : (
          <NavLink to="/login">Login</NavLink>
        )}
      </nav>
      <div className="navActions">
        {user && (
          <div className="navIdentity">
            <small>
              {user.is_superuser ? "Owner" : user.is_staff ? "Staff" : "Customer"}
            </small>
            <button className="linkButton" onClick={() => void signOut()}>
              Logout
            </button>
          </div>
        )}
        <ThemePicker />
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
