import { ThemeSync } from "./core/ui/theme";
import { PlatformProvider } from "./modules/platform/PlatformContext";
import { AppRoutes } from "./routes/AppRoutes";
import { usePreventNumberScroll } from "./core/forms/usePreventNumberScroll";
export default function App() {
  usePreventNumberScroll();
  return <PlatformProvider><ThemeSync /><AppRoutes /></PlatformProvider>;
}
