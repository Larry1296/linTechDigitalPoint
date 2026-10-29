import { useTranslation, setLanguage } from "../core/i18n";
import { BackLink } from "../components/navigation/BackLink";
import { ThemePicker } from "../components/ThemePicker";
import "./workspace.css";
import { useMediaQuery } from "../core/ui/useMediaQuery";
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
  Users, BedDouble, ChefHat, ConciergeBell, UtensilsCrossed, BookUser } from "lucide-react";
import { Outlet } from "react-router-dom";
import { useKeyboardShortcuts } from "../core/ui/keyboardShortcuts";
import { SubscriptionBanner } from "../modules/billing/SubscriptionBanner";
import { useEffect, useRef, useState } from "react";
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
// A hotel's rooms and its kitchen: the front desk and guests, then the menu and what the kitchen used.
const hotelLinks = [
  { to: "/admin/rooms", label: "Front desk", icon: ConciergeBell, permission: "hotel.view_stay", end: true },
  { to: "/admin/rooms/guests", label: "Guests & bookings", icon: BookUser, permission: "hotel.view_stay" },
  { to: "/admin/rooms/setup", label: "Rooms & prices", icon: BedDouble, permission: "hotel.view_room" },
  { to: "/admin/menu", label: "Menu", icon: UtensilsCrossed, permission: "hotel.view_menuitem" },
  { to: "/admin/kitchen", label: "Kitchen", icon: ChefHat, permission: "hotel.view_kitchenuse" },
];
const operations = [
  { title: "Overview", links: [links[0]] },
  { title: "Hotel", icon: BedDouble, collapsible: true, links: hotelLinks },
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
  // Phones and tablets: the sidebar is a drawer opened by the topbar's menu button. It remembers the page it
  // was opened on, so going to another page closes it.
  const [openOn, setOpenOn] = useState(null);
  const compact = useMediaQuery("(max-width: 1023px)");
  const drawerOpen = compact && openOn === pathname;
  const [switchError, setSwitchError] = useState("");
  const topbarRef = useRef(null);
  const sidebarRef = useRef(null);
  const menuButtonRef = useRef(null);
  useKeyboardShortcuts();
  useEffect(() => {
    const bar = topbarRef.current;
    if (!bar || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => document.documentElement.style.setProperty("--workspace-topbar-height", `${Math.ceil(bar.getBoundingClientRect().height)}px`));
    observer.observe(bar);
    return () => { observer.disconnect(); document.documentElement.style.removeProperty("--workspace-topbar-height"); };
  }, []);
  // While the drawer is open the page behind it stays still, Escape closes it, and focus starts on its first link.
  useEffect(() => {
    if (!drawerOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    (sidebarRef.current?.querySelector("nav a.active") || sidebarRef.current?.querySelector("nav a, nav button"))?.focus({ preventScroll: true });
    const onKey = (event) => { if (event.key === "Escape") { setOpenOn(null); menuButtonRef.current?.focus(); } };
    document.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", onKey); };
  }, [drawerOpen]);
  function closeDrawer() {
    setOpenOn(null);
    menuButtonRef.current?.focus();
  }
  const organization = user.organization;
  const moduleFor = {"/admin/quick-receive":"inventory", "/admin/opening-stock":"inventory", "/admin/expenses":"expenses","/admin/product-lookup":"inventory", "/admin/pos":"pos", "/admin/products":"inventory", "/admin/receive":"inventory", "/admin/receipts":"inventory", "/admin/adjust-stock":"inventory", "/admin/stock-check":"inventory", "/admin/categories":"inventory", "/admin/brands":"inventory", "/admin/shelf-management":"locations", "/admin/cyber":"services", "/admin/cyber/income":"services", "/admin/mpesa":"mpesa", "/admin/mpesa/commission":"mpesa", "/admin/investments":"investments", "/admin/reports":"reports", "/admin/chama":"chama", "/admin/rooms":"rooms", "/admin/rooms/guests":"rooms", "/admin/rooms/setup":"rooms", "/admin/menu":"menu", "/admin/kitchen":"menu"};
  // The services part is named for this business: "Cyber Services" only for a cyber, else the name its owner gave it.
  const servicesPart = organization.parts?.find((part) => part.key === "CYBER")?.name;
  const servicesTitle = servicesPart && servicesPart !== "Cyber" ? (/services?$/i.test(servicesPart) ? servicesPart : `${servicesPart} services`)
    : (organization.sector || "").includes("cyber") ? "Cyber Services" : "Services";
  const planLabel = organization.subscription?.complimentary ? "Pro" : organization.subscription?.ended ? "Renew" : `${organization.subscription?.plan_name || "Plan"}${organization.subscription?.days_left != null ? ` · ${organization.subscription.days_left}d` : ""}`;
  const switchers = <>
    {user.memberships.length > 1 && <label className="workspaceBusiness">Organization <select aria-label="Active organization" value={organization.id} onChange={event => switchBusiness(event.target.value).then(() => window.location.assign("/admin/dashboard")).catch(error=>setSwitchError(error.message))}>{user.memberships.map(({organization})=><option key={organization.id} value={organization.id}>{organization.name}</option>)}</select></label>}
    {user.branches?.length > 0 && <label className="workspaceBusiness">Branch <select aria-label="Active branch" value={user.branch?.id || user.branches[0].id} onChange={event => switchBranch(event.target.value).then(() => window.location.assign(window.location.pathname)).catch(error=>setSwitchError(error.message))}>{user.branches.map(branch=><option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>}
  </>;
  const language = <label className="workspaceLanguage">Language<select value={locale} onChange={e => setLanguage(e.target.value)}><option value="en">English</option><option value="sw">Kiswahili</option></select></label>;
  const lockButton = <button type="button" className="workspaceLock" onClick={lock} aria-label="Lock workspace" title="Lock workspace"><LockKeyhole size={18} aria-hidden="true" /><span className="workspaceLockLabel">Lock workspace</span></button>;
  return (
    <>
      <header ref={topbarRef} className="workspaceTopbar" aria-label="Business topbar">
        {compact && <button ref={menuButtonRef} className="workspaceMenu" type="button" aria-label={drawerOpen ? "Close dashboard menu" : "Open dashboard menu"} aria-expanded={drawerOpen} aria-controls="business-sidebar" onClick={() => setOpenOn(drawerOpen ? null : pathname)}>
          {drawerOpen ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
        </button>}
        <Link className="workspaceBrand" to="/admin/dashboard">
          <BusinessBrand organization={organization} compact />
        </Link>
        {/* Phones and tablets keep only what the page needs: the menu, the business and the lock. */}
        {compact ? lockButton : <>
          {switchers}
          <div className="workspaceActions">{lockButton}
            <Link className="workspacePlan" to="/admin/subscription">{planLabel}</Link>
            <Link className="workspaceHelp" to="/#contact">Help</Link>
            {language}<ThemePicker />
          </div>
        </>}
        {switchError && <p role="alert">{switchError}</p>}
      </header>
      <div className="admin">
        {drawerOpen && <button className="sidebarBackdrop" type="button" tabIndex={-1} aria-label="Close dashboard menu" onClick={closeDrawer} />}
        <aside ref={sidebarRef} id="business-sidebar" className={drawerOpen ? "sidebarOpen" : undefined} aria-label="Dashboard menu" aria-hidden={compact && !drawerOpen ? true : undefined} inert={compact && !drawerOpen ? true : undefined}>
          {compact && <div className="sidebarHeader">
            <Link className="sidebarBrand" to="/admin/dashboard"><BusinessBrand organization={organization} compact /></Link>
            <button className="sidebarClose" type="button" aria-label="Close dashboard menu" onClick={closeDrawer}><X size={22} aria-hidden="true" /></button>
          </div>}
          <div className="sidebarBody">
            <SidebarNavigation
              sections={operations.map((section) => ({
                ...section,
                title: section.links === cyberLinks ? servicesTitle : section.links === hotelLinks && !organization.enabled_modules.includes("rooms") ? "Kitchen & menu" : section.title,
                links: section.links.filter(
                  (item) =>
                    (!moduleFor[item.to] || organization.enabled_modules.includes(moduleFor[item.to])) &&
                    (!item.permission || user?.permissions.includes(item.permission)) &&
                    (!item.platformAdmin || user.platform_admin) &&
                    (!item.managers || ["OWNER", "ADMIN"].includes(user.roles?.[0])),
                ),
              }))}
              onNavigate={() => setOpenOn(null)}
            />
            {/* The topbar's other controls live here on phones and tablets. */}
            {compact && <div className="sidebarTopbarControls">
              {switchers}
              <div className="sidebarQuickLinks">
                <Link className="workspacePlan" to="/admin/subscription"><CreditCard size={16} aria-hidden="true" />{planLabel}</Link>
                <Link className="workspaceHelp" to="/#contact">Help</Link>
              </div>
              <div className="sidebarPreferences">{language}<ThemePicker /></div>
            </div>}
            <SidebarAccount />
          </div>
        </aside>
        <main inert={drawerOpen ? true : undefined}>
          {!(["/admin/products", "/admin/product-lookup", "/admin/categories"].includes(pathname)) && <BackLink />}
          <SubscriptionBanner organization={organization} canManage={["OWNER", "ADMIN"].includes(user.roles?.[0])} />
          <Outlet />
        </main>
      </div>
      {organization && <BusinessAssistant key={organization.id} organization={organization} />}
      <AppFooter />
    </>
  );
}
