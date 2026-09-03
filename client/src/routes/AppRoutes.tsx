import { Navigate, Route, Routes } from "react-router-dom";
import { PublicLayout } from "../layouts/PublicLayout";
import { StaffLayout } from "../layouts/StaffLayout";
import {
  AccountPage,
  OrderDetailPage,
  OrdersPage,
} from "../modules/customer/AccountPage";
import {
  AddressesPage,
  PasswordResetPage,
} from "../modules/customer/AccountExtras";
import { CheckoutPage } from "../modules/customer/CheckoutPage";
import { LoginPage, RegisterPage } from "../modules/auth/AuthPages";
import { CartPage } from "../modules/storefront/CartPage";
import { HomePage } from "../modules/storefront/HomePage";
import { ProductPage } from "../modules/storefront/ProductPage";
import { ShopPage } from "../modules/storefront/ShopPage";
import {
  AnalyticsPage,
  DashboardPage,
  PosPage,
  ProductsAdminPage,
  ReceivePage,
  StaffOrdersPage,
} from "../modules/admin/AdminPages";
import { DigitalShopPage } from "../modules/admin/DigitalShopPage";
import { CustomerProtectedRoute, StaffProtectedRoute } from "./ProtectedRoutes";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route index element={<HomePage />} />
        <Route path="shop" element={<ShopPage />} />
        <Route path="products/:id" element={<ProductPage />} />
        <Route path="cart" element={<CartPage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="password-reset" element={<PasswordResetPage />} />
        <Route
          path="checkout"
          element={
            <CustomerProtectedRoute>
              <CheckoutPage />
            </CustomerProtectedRoute>
          }
        />
        <Route
          path="account"
          element={
            <CustomerProtectedRoute>
              <AccountPage />
            </CustomerProtectedRoute>
          }
        />
        <Route
          path="account/addresses"
          element={
            <CustomerProtectedRoute>
              <AddressesPage />
            </CustomerProtectedRoute>
          }
        />
        <Route
          path="account/orders"
          element={
            <CustomerProtectedRoute>
              <OrdersPage />
            </CustomerProtectedRoute>
          }
        />
        <Route
          path="account/orders/:id"
          element={
            <CustomerProtectedRoute>
              <OrderDetailPage />
            </CustomerProtectedRoute>
          }
        />
        <Route
          path="forbidden"
          element={
            <main className="state">
              <h1>403</h1>
              <p>You do not have permission to view this page.</p>
            </main>
          }
        />
      </Route>
      <Route
        path="admin-app"
        element={
          <StaffProtectedRoute>
            <StaffLayout />
          </StaffProtectedRoute>
        }
      >
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="pos" element={<PosPage />} />
        <Route path="orders" element={<StaffOrdersPage />} />
        <Route path="products" element={<ProductsAdminPage />} />
        <Route path="receive" element={<ReceivePage />} />
        <Route path="digital-shop" element={<DigitalShopPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
