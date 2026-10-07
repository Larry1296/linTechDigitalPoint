import { useTranslation, setLanguage } from "../core/i18n";
import { BackLink } from "../components/navigation/BackLink";
import { ThemePicker } from "../components/ThemePicker";
import "./workspace.css";
import { switchBusiness, switchBranch } from "../modules/platform/Onboarding";
import { Link, useLocation } from "react-router-dom";
import { SidebarNavigation } from "../components/navigation/SidebarNavigation";
import { SidebarAccount } from "../components/navigation/SidebarAccount";
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
  Tags,
  BadgeCheck,
  LockKeyhole,
  Menu,
  X,
  CreditCard,
  ShieldCheck,
  Sparkles,
  HandCoins,
  PiggyBank,
  ClipboardCheck,
  Wallet,
  Coins,
  Store,
  Briefcase,
  Users,
} from "lucide-react";
import { Outlet } from "react-router-dom";
import { SubscriptionBanner } from "../modules/billing/SubscriptionBanner";
import { useEffect, useRef, useState } from "react";
import { useTableLabels } from "../core/ui/useTableLabels";
import { useAuth } from "../core/auth/AuthContext";
import { AppFooter } from "../components/AppChrome";
import { BusinessBrand } from "../components/Brand";
import { BusinessAssistant } from "../modules/assistant/BusinessAssistant";
const links = [
  {
    to: "/admin/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    permission: null,
  },
  {
    to: "/admin/pos",
    label: "Point of Sale",
    icon: ShoppingCart,
    permission: "commerce.add_sale",
  },
  {
    to: "/admin/product-lookup",
    label: "Product Lookup",
    icon: Box,
    permission: "catalog.view_product",
  },
  {
    to: "/admin/products",
    label: "Products",
    icon: Box,
    permission: "catalog.view_product",
  },
  {
    to: "/admin/quick-receive",
    label: "Receive Stock",
    icon: PackagePlus,
    permission: "inventory.add_stocklot",
  },
  {
    to: "/admin/shelf-management",
    label: "Shelf Management",
    icon: Map,
    permission: "inventory.view_shelf",
  },
  {
    to: "/admin/reports",
    label: "Reports",
    icon: BarChart3,
    permission: "accounting.view_profit",
  },
];
const lookupLinks = [links[2]];
const inventoryLinks = [
  links[3],
  { to: "/admin/categories", label: "Categories", icon: Tags, permission: "catalog.view_category" },
  { to: "/admin/brands", label: "Brands", icon: BadgeCheck, permission: "catalog.view_brand" },
  { to: "/admin/opening-stock", label: "Stock I Already Have", icon: PackagePlus, permission: "inventory.add_stockreceipt" },
  links[4],
  { to: "/admin/receipts", label: "Recent Receipts", icon: Receipt, permission: "inventory.view_stockreceipt" },
  { to: "/admin/stock-check", label: "Stock check", icon: ClipboardCheck, permission: "inventory.adjust_stock" },
  { to: "/admin/adjust-stock", label: "Stock Adjustments", icon: PackagePlus, permission: "inventory.adjust_stock" },
  links[5],
];
// The sidebar: Dashboard, then one group per kind of business (each shown only when that business is switched on),
// then the money and settings that cover all of them.
const shopLinks = [
  links[1],
  { to: "/admin/sales-history", label: "Sales History", icon: Receipt, permission: "commerce.view_sale" },
  ...lookupLinks,
  ...inventoryLinks,
];
const businessLinks = [links[6], { to: "/admin/expenses", label: "Money spent", icon: Receipt, permission: "accounting.add_expense" }, { to: "/admin/money-lent", label: "Money lent", icon: HandCoins, permission: "accounting.view_loan" }, { to: "/admin/investments", label: "Investments", icon: PiggyBank, permission: "accounting.view_investment" }, { to: "/admin/money-check", label: "Money check", icon: Wallet, permission: "accounting.view_moneycheck" }, { to: "/admin/subscription", label: "Subscription", icon: CreditCard, permission: null, managers: true }, { to: "/admin/settings", label: "Settings", icon: MonitorCog, permission: null }];
// Each service opens as a full page from Income by service, so the menu stays short.
const cyberLinks = [
  { to: "/admin/cyber", label: "Service Desk", icon: MonitorCog, permission: "cyber.view_cyberjob", end: true },
  { to: "/admin/cyber/income", label: "Income by service", icon: Coins, permission: "cyber.view_cyberjob" },
];
const operations = [
  { title: "Overview", links: [links[0]] },
  { title: "Shop Management", icon: Store, collapsible: true, links: shopLinks },
  { title: "Cyber Services", icon: MonitorCog, collapsible: true, links: cyberLinks },
  { title: "M-Pesa Agent", icon: Smartphone, collapsible: true, links: [{ to: "/admin/mpesa", label: "Agent desk", icon: Smartphone, permission: "mpesa.view_mpesasession", end: true }, { to: "/admin/mpesa/commission", label: "Commission", icon: Coins, permission: "mpesa.view_mpesacommissionentry" }] },
  // A chama is not part of the shop: its own group, apart from the shop's money under Business.
  { title: "Chama", icon: Users, collapsible: true, links: [{ to: "/admin/chama", label: "My chama", icon: Users, permission: "chama.view_chama" }] },
  { title: "Business", icon: Briefcase, collapsible: true, links: businessLinks },
  { title: "Platform", links: [{ to: "/admin/platform", label: "All businesses", icon: ShieldCheck, permission: null, platformAdmin: true, end: true },
    { to: "/admin/platform/assistants", label: "AI assistants", icon: Sparkles, permission: null, platformAdmin: true }] },
];
export function StaffLayout() {
  const { locale } = useTranslation();
  const { pathname } = useLocation();
  const { user, lock } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const mainRef = useRef(null);
  const topbarRef = useRef(null);
  useTableLabels(mainRef);
  useEffect(() => {
    const bar = topbarRef.current;
    if (!bar || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => document.documentElement.style.setProperty("--workspace-topbar-height", `${Math.ceil(bar.getBoundingClientRect().height)}px`));
    observer.observe(bar);
    return () => { observer.disconnect(); document.documentElement.style.removeProperty("--workspace-topbar-height"); };
  }, []);
  const organization = user.organization;
  const moduleFor = {"/admin/quick-receive":"inventory", "/admin/opening-stock":"inventory", "/admin/expenses":"expenses","/admin/product-lookup":"inventory", "/admin/pos":"pos", "/admin/products":"inventory", "/admin/receive":"inventory", "/admin/receipts":"inventory", "/admin/adjust-stock":"inventory", "/admin/stock-check":"inventory", "/admin/categories":"inventory", "/admin/brands":"inventory", "/admin/shelf-management":"locations", "/admin/cyber":"services", "/admin/cyber/income":"services", "/admin/mpesa":"mpesa", "/admin/mpesa/commission":"mpesa", "/admin/reports":"reports"};
  return (
    <>
      <header ref={topbarRef} className="workspaceTopbar" aria-label="Business topbar">
        <button className="workspaceMenu" type="button" aria-label={sidebarOpen ? "Close dashboard menu" : "Open dashboard menu"} aria-expanded={sidebarOpen} aria-controls="business-sidebar" onClick={() => setSidebarOpen(open => !open)}>
          {sidebarOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
        <Link className="workspaceBrand" to="/admin/dashboard">
        <BusinessBrand organization={organization} compact />
        </Link>
        {user.memberships.length > 1 && <label className="workspaceBusiness">Organization <select aria-label="Active organization" value={organization.id} onChange={event => switchBusiness(event.target.value).then(() => window.location.assign("/admin/dashboard")).catch(error=>setSwitchError(error.message))}>{user.memberships.map(({organization})=><option key={organization.id} value={organization.id}>{organization.name}</option>)}</select></label>}
        {user.branches?.length > 0 && <label className="workspaceBusiness">Branch <select aria-label="Active branch" value={user.branch?.id || user.branches[0].id} onChange={event => switchBranch(event.target.value).then(() => window.location.assign(window.location.pathname)).catch(error=>setSwitchError(error.message))}>{user.branches.map(branch=><option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>}
        <div className="workspaceActions"><button type="button" className="workspaceLock" onClick={lock} aria-label="Lock workspace"><LockKeyhole size={18} aria-hidden="true" /><span className="workspaceLockLabel">Lock workspace</span></button>
          <Link className="workspacePlan" to="/admin/subscription">{organization.subscription?.complimentary ? "Pro" : organization.subscription?.ended ? "Renew" : `${organization.subscription?.plan_name || "Plan"}${organization.subscription?.days_left != null ? ` · ${organization.subscription.days_left}d` : ""}`}</Link>
          <Link className="workspaceHelp" to="/#contact">Help</Link>
          <label>Language<select value={locale} onChange={e => setLanguage(e.target.value)}><option value="en">English</option><option value="sw">Kiswahili</option></select></label><ThemePicker />
        </div>
        {switchError && <p role="alert">{switchError}</p>}
      </header>
      <div className="admin">
        <aside id="business-sidebar" className={sidebarOpen ? "sidebarOpen" : undefined} onKeyDown={event => { if (event.key === "Escape") { setSidebarOpen(false); document.querySelector(".workspaceMenu")?.focus(); } }}>
          <button
            className="sidebarClose"
            type="button"
            aria-label="Close dashboard menu"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={24} aria-hidden="true" />
          </button>
          <SidebarNavigation
            sections={operations.map((section) => ({
              ...section,
              links: section.links.filter(
                (item) =>
                  (!moduleFor[item.to] || organization.enabled_modules.includes(moduleFor[item.to])) &&
                  (!item.permission || user?.permissions.includes(item.permission)) &&
                  (!item.platformAdmin || user.platform_admin) &&
                  (!item.managers || ["OWNER", "ADMIN"].includes(user.roles?.[0])),
              ),
            }))}
            onNavigate={() => setSidebarOpen(false)}
          />
          <SidebarAccount />
        </aside>
        <main ref={mainRef}>
          {!(["/admin/products", "/admin/product-lookup"].includes(pathname)) && <BackLink />}
          <SubscriptionBanner organization={organization} canManage={["OWNER", "ADMIN"].includes(user.roles?.[0])} />
          <Outlet />
        </main>
      </div>
      {organization && <BusinessAssistant key={organization.id} organization={organization} />}
      <AppFooter />
    </>
  );
}
