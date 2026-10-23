import { ThemeSync } from "./core/ui/theme";
import { PlatformProvider } from "./modules/platform/PlatformContext";
import { AppRoutes } from "./routes/AppRoutes";
import { usePreventNumberScroll } from "./core/forms/usePreventNumberScroll";
import { CapsLockWarning } from "./components/forms/CapsLockWarning";
import { useTableLabels } from "./core/ui/useTableLabels";
export default function App() {
  usePreventNumberScroll();
  // On phones and tablets every table row is a card, each figure labelled with its column heading.
  useTableLabels();
  return <PlatformProvider><ThemeSync /><AppRoutes /><CapsLockWarning /></PlatformProvider>;
}
