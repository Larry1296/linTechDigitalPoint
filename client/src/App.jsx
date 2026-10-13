import { ThemeSync } from "./core/ui/theme";
import { PlatformProvider } from "./modules/platform/PlatformContext";
import { AppRoutes } from "./routes/AppRoutes";
import { usePreventNumberScroll } from "./core/forms/usePreventNumberScroll";
import { CapsLockWarning } from "./components/forms/CapsLockWarning";
export default function App() {
  usePreventNumberScroll();
  return <PlatformProvider><ThemeSync /><AppRoutes /><CapsLockWarning /></PlatformProvider>;
}
