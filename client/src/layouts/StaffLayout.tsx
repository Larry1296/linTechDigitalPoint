import {
  BarChart3,
  Box,
  LayoutDashboard,
  Map,
  PackagePlus,
  Receipt,
  ShoppingCart,
  MonitorCog,
  Smartphone,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
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
const operations = [
  { title: "Overview", links: [links[0]] },
  { title: "Sales", links: [links[1], links[2]] },
  { title: "Cyber", links: [
    { to: "/admin-app/cyber", label: "Cyber Desk", icon: MonitorCog, permission: "cyber.view_cyberjob" },
  ] },
  { title: "M-Pesa", links: [
    { to: "/admin-app/mpesa", label: "M-Pesa Agent", icon: Smartphone, permission: "mpesa.view_mpesasession" },
  ] },
  { title: "Inventory", links: [links[3], links[4], links[5]] },
  { title: "Business", links: [links[6]] },
];
export function StaffLayout() {
  const { user } = useAuth();
  return (
    <>
      <AppNavbar />
      <div className="admin">
        <aside>
          <nav>
            {operations.map((section) => {
              const visible = section.links.filter((item) => !item.permission || user?.is_superuser || user?.permissions.includes(item.permission));
              return visible.length ? <section key={section.title}><small>{section.title.toUpperCase()}</small>{visible.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to}><Icon />{label}</NavLink>)}</section> : null;
            })}
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
