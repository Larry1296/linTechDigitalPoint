import { ShoppingCart } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { useCart } from "../core/cart/CartContext";
import { ThemePicker } from "./ThemePicker";

function can(permission: string, user: ReturnType<typeof useAuth>["user"]) {
  return Boolean(user?.is_superuser || user?.permissions.includes(permission));
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
        LinTech<span>Digital Point</span>
      </Link>
      <nav aria-label="Main navigation">
        {user?.is_staff ? (
          <>
            <NavLink to="/">Storefront</NavLink>
            <NavLink to="/admin-app/dashboard">Dashboard</NavLink>
            {can("commerce.add_sale", user) && (
              <NavLink to="/admin-app/pos">POS</NavLink>
            )}
            {can("commerce.view_order", user) && (
              <NavLink to="/admin-app/orders">Orders</NavLink>
            )}
            {can("catalog.view_product", user) && (
              <NavLink to="/admin-app/products">Products</NavLink>
            )}
          </>
        ) : (
          <>
            <NavLink to="/">Home</NavLink>
            <NavLink to="/shop">Shop</NavLink>
            <Link to="/#categories">Categories</Link>
            <Link to="/#services">Services</Link>
            <NavLink to="/cart">
              <ShoppingCart size={18} /> Cart{" "}
              <span className="cartBadge">{count}</span>
            </NavLink>
            {user ? (
              <>
                <NavLink to="/account">My Account</NavLink>
                <NavLink to="/account/orders">Orders</NavLink>
              </>
            ) : (
              <NavLink to="/login">Login</NavLink>
            )}
          </>
        )}
      </nav>
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
    </header>
  );
}

export function AppFooter() {
  const { user } = useAuth();
  return (
    <footer className="appFooter">
      <div>
        <Link className="brand" to="/">
          LinTech<span>Digital Point</span>
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
      <ThemePicker />
    </footer>
  );
}
