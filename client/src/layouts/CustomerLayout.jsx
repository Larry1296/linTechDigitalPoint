import {
  LayoutDashboard,
  MapPin,
  Receipt,
  ShoppingBag,
  ShoppingCart,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { AppFooter, AppNavbar } from "../components/AppChrome";
import { ThemePicker } from "../components/ThemePicker";
import { useAuth } from "../core/auth/AuthContext";
import { useCart } from "../core/cart/CartContext";
import { confirmAction } from "../core/ui/alerts";

const sections = [
  {
    title: "My account",
    links: [
      { to: "/account", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/account/orders", label: "Orders", icon: Receipt },
      { to: "/account/addresses", label: "Addresses", icon: MapPin },
    ],
  },
  {
    title: "Shopping",
    links: [
      { to: "/cart", label: "Cart", icon: ShoppingCart },
      { to: "/shop", label: "Shop", icon: ShoppingBag },
    ],
  },
];

function subscribeToViewport(onChange) {
  const media = window.matchMedia("(max-width: 760px)");
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

export function CustomerLayout() {
  const isMobile = useSyncExternalStore(
    subscribeToViewport,
    () => window.matchMedia("(max-width: 760px)").matches,
    () => false,
  );
  const location = useLocation();
  const { user, logout } = useAuth();
  const { refreshCart } = useCart();
  const sidebarRef = useRef(null);
  const [openLocation, setOpenLocation] = useState(null);
  const toggleRef = useRef(null);
  const sidebarOpen = openLocation === location.key;

  useEffect(() => {
    if (!sidebarOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebarRef.current?.querySelector("a")?.focus();
    const close = (event) => {
      if (event.key === "Escape") {
        setOpenLocation(null);
        toggleRef.current?.focus();
      }
    };
    const desktop = window.matchMedia("(min-width: 761px)");
    const onResize = () => {
      if (desktop.matches) setOpenLocation(null);
    };
    document.addEventListener("keydown", close);
    desktop.addEventListener("change", onResize);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", close);
      desktop.removeEventListener("change", onResize);
    };
  }, [sidebarOpen]);

  return (
    <>
      <AppNavbar
        accountMenuRef={toggleRef}
        accountMenu={{
          open: sidebarOpen,
          mobile: isMobile,
          toggle: () => setOpenLocation(sidebarOpen ? null : location.key),
        }}
      />
      <div className="customerDashboard">
        {sidebarOpen && (
          <button
            className="customerSidebarBackdrop"
            type="button"
            aria-label="Dismiss account menu"
            onClick={() => {
              setOpenLocation(null);
              toggleRef.current?.focus();
            }}
          />
        )}
        <aside
          ref={sidebarRef}
          id="customer-sidebar"
          className={`customerSidebar${sidebarOpen ? " isOpen" : ""}`}
        >
          <button
            className="customerSidebarClose"
            type="button"
            aria-label="Close account menu"
            onClick={() => {
              setOpenLocation(null);
              toggleRef.current?.focus();
            }}
          >
            <X size={24} aria-hidden="true" />
          </button>
          <nav aria-label="Customer account navigation">
            {sections.map(({ title, links }) => (
              <section key={title}>
                <small>{title.toUpperCase()}</small>
                {links.map(({ to, label, icon: Icon, end }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    onClick={() => setOpenLocation(null)}
                  >
                    <Icon size={19} aria-hidden="true" />
                    {label}
                  </NavLink>
                ))}
              </section>
            ))}
          </nav>
          {isMobile && (
            <div className="customerMobileActions">
              <span className="navUserName">
                {user?.first_name || user?.username} (Customer)
              </span>
              <ThemePicker />
              <button
                type="button"
                onClick={async () => {
                  if (
                    !(await confirmAction({
                      title: "Sign out?",
                      text: "You will need to sign in again to access your account.",
                      confirmButtonText: "Sign out",
                      icon: "question",
                    }))
                  )
                    return;
                  await logout();
                  await refreshCart();
                }}
              >
                Logout
              </button>
            </div>
          )}
        </aside>
        <main inert={sidebarOpen}>
          <Outlet />
        </main>
      </div>
      <AppFooter />
    </>
  );
}
