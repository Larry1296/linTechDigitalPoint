import { Outlet } from "react-router-dom";
import { AppFooter, AppNavbar } from "../components/AppChrome";
export function PublicLayout() {
  return (
    <>
      <AppNavbar />
      <Outlet />
      <AppFooter />
    </>
  );
}
