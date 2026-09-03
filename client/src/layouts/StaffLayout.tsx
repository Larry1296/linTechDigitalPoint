import {
  BarChart3,
  Box,
  LayoutDashboard,
  Map,
  PackagePlus,
  Receipt,
  ShoppingCart,
} from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../core/auth/AuthContext";
import { AppFooter, AppNavbar } from "../components/AppChrome";
const links = [
  {
    to: "/admin-app/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    permission: null,
  },
  {
    to: "/admin-app/pos",
    label: "Point of Sale",
    icon: ShoppingCart,
    permission: "commerce.add_sale",
  },
  {
    to: "/admin-app/orders",
    label: "Ecommerce Orders",
    icon: Receipt,
    permission: "commerce.view_order",
  },
  {
    to: "/admin-app/products",
    label: "Products",
    icon: Box,
    permission: "catalog.view_product",
  },
  {
    to: "/admin-app/receive",
    label: "Receive Stock",
    icon: PackagePlus,
    permission: "inventory.add_stocklot",
  },
  {
    to: "/admin-app/digital-shop",
    label: "Digital Shop",
    icon: Map,
    permission: "inventory.view_shelf",
  },
  {
    to: "/admin-app/analytics",
    label: "Analytics",
    icon: BarChart3,
    permission: "commerce.view_sale",
  },
];
export function StaffLayout() {
  const { user } = useAuth();
  const visible = links.filter(
    (x) =>
      !x.permission ||
      user?.is_superuser ||
      user?.permissions.includes(x.permission),
  );
  return (
    <>
      <AppNavbar />
      <div className="admin">
        <aside>
          <Link className="brand" to="/">
            LinTech<span>Digital Point</span>
          </Link>
          <nav>
            {visible.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to}>
                <Icon />
                {label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main>
          <Outlet />
        </main>
      </div>
      <AppFooter />
    </>
  );
}
