import {
  LayoutDashboard,
  MapPin,
  Receipt,
  ShoppingBag,
  ShoppingCart,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AppFooter, AppNavbar } from "../components/AppChrome";
import { ThemePicker } from "../components/ThemePicker";
import { SidebarNavigation } from "../components/navigation/SidebarNavigation";
import { SidebarAccount } from "../components/navigation/SidebarAccount";
import { useMediaQuery } from "../core/ui/useMediaQuery";

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

export function CustomerLayout() {
  const isMobile = useMediaQuery("(max-width: 760px)");
  const location = useLocation();
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
          <SidebarNavigation
            sections={sections}
            label="Customer account navigation"
            iconSize={19}
            onNavigate={() => setOpenLocation(null)}
          />
          <SidebarAccount>{isMobile && <ThemePicker />}</SidebarAccount>
        </aside>
        <main inert={sidebarOpen}>
          <Outlet />
        </main>
      </div>
      <AppFooter />
    </>
  );
}
