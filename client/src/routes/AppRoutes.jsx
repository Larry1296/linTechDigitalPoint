import { SalesPage } from "../modules/admin/SalesPage";
import { QuickReceivePage } from "../modules/receiving/QuickReceivePage";
import { LedgerPage, ExpensesPage } from "../modules/admin/LedgerPage";
import { AccountingReportsPage } from "../modules/admin/AccountingReportsPage";
import { ProductLookupPage } from "../modules/products/ProductLookupPage";
import { PublicHome } from "../modules/platform/PublicSite";
import { PublicReceiptPage } from "../modules/receipts/PublicReceiptPage";
import { RegisterPage, OnboardingPage, SelectBusinessPage, ForgotPasswordPage, ResetPasswordPage } from "../modules/platform/Onboarding";
import { SubscriptionPage } from "../modules/billing/SubscriptionPage";
import { MoneyLentPage } from "../modules/loans/MoneyLentPage";
import { InvestmentsPage } from "../modules/investments/InvestmentsPage";
import { MoneyCheckPage } from "../modules/accounting/MoneyCheckPage";
import { StockCheckPage } from "../modules/inventory/StockCheckPage";
import { PlatformAdminPage } from "../modules/billing/PlatformAdminPage";
import { SettingsPage } from "../modules/settings/SettingsPage";
import { ReceiptHistoryPage } from "../modules/inventory/ReceiptHistoryPage";
import { StockAdjustmentPage } from "../modules/inventory/StockAdjustmentPage";
import { Navigate, Route, Routes } from "react-router-dom";
import { StaffLayout } from "../layouts/StaffLayout";
import { LoginPage } from "../modules/auth/AuthPages";
import {
  AnalyticsPage,
  DashboardPage,
  PosPage,
} from "../modules/admin/AdminPages";
import { DigitalShopPage } from "../modules/digital-shop/DigitalShopPage";
import { CategoriesPage } from "../modules/digital-shop/CategoriesPage";
import { BrandsPage } from "../modules/products/BrandsPage";
import { ProductsPage } from "../modules/products/ProductsPage";
import { ReceivePage } from "../modules/receiving/ReceivePage";
import { StaffProtectedRoute } from "./ProtectedRoutes";
import { CyberDashboardPage } from "../modules/cyber/CyberDashboardPage";
import { CyberIncomePage, CyberServiceIncomePage } from "../modules/cyber/CyberIncomePage";
import { MpesaDashboardPage } from "../modules/mpesa/MpesaDashboardPage";
import { MpesaCommissionPage } from "../modules/mpesa/MpesaCommissionPage";
import { KyamaDetailPage, KyamaHomePage, KyamaSetupPage } from "../modules/kyama/KyamaPages";
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<PublicHome />} />
      {["features", "pricing", "about", "contact"].map(path => <Route key={path} path={`/${path}`} element={<PublicHome />} />)}
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />
      <Route path="/select-business" element={<SelectBusinessPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/password-reset" element={<ForgotPasswordPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/r/:token" element={<PublicReceiptPage />} />
      <Route
        path="/admin"
        element={
          <StaffProtectedRoute>
            <StaffLayout />
          </StaffProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/admin/dashboard" replace />} />
        <Route path="subscription" element={<SubscriptionPage />} />
        <Route path="money-lent" element={<MoneyLentPage />} />
        <Route path="investments" element={<InvestmentsPage />} />
        <Route path="money-check" element={<MoneyCheckPage />} />
        <Route path="stock-check" element={<StockCheckPage />} />
        <Route path="platform" element={<PlatformAdminPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="product-lookup" element={<ProductLookupPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="pos" element={<PosPage />} />
        <Route path="quick-receive" element={<QuickReceivePage key="purchase" />} />
        <Route path="opening-stock" element={<QuickReceivePage key="opening" defaultSource="OPENING" />} />
        <Route path="receive" element={<ReceivePage />} />
        <Route path="receipts" element={<ReceiptHistoryPage />} />
        <Route path="receipts/:id" element={<ReceiptHistoryPage />} />
        <Route path="adjust-stock" element={<StockAdjustmentPage />} />
        <Route path="shelf-management" element={<DigitalShopPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="brands" element={<BrandsPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="reports" element={<AccountingReportsPage />} />
        <Route path="reports/journals" element={<LedgerPage />} />
        <Route path="expenses" element={<ExpensesPage />} />
        <Route path="sales-history" element={<SalesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="cyber" element={<CyberDashboardPage />} />
        <Route path="cyber/jobs" element={<CyberDashboardPage />} />
        <Route path="cyber/services" element={<CyberDashboardPage />} />
        <Route path="cyber/income" element={<CyberIncomePage />} />
        <Route path="cyber/income/:serviceId" element={<CyberServiceIncomePage />} />
        <Route path="mpesa" element={<MpesaDashboardPage />} />
        <Route path="mpesa/transactions" element={<MpesaDashboardPage />} />
        <Route path="mpesa/reconciliation" element={<MpesaDashboardPage />} />
        <Route path="mpesa/commission" element={<MpesaCommissionPage />} />
        <Route path="kyama" element={<KyamaHomePage />} />
        <Route path="kyama/setup" element={<KyamaSetupPage />} />
        <Route path="kyama/:id" element={<KyamaDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
