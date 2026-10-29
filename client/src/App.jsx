import { ThemeSync } from "./core/ui/theme";
import { PlatformProvider } from "./modules/platform/PlatformContext";
import { AppRoutes } from "./routes/AppRoutes";
import { usePreventNumberScroll } from "./core/forms/usePreventNumberScroll";
import { CapsLockWarning } from "./components/forms/CapsLockWarning";
import { useTableLabels } from "./core/ui/useTableLabels";
import { useReloadOnNewRelease } from "./core/release";
export default function App() {
  usePreventNumberScroll();
  // On phones and tablets every table row is a card, each figure labelled with its column heading.
  useTableLabels();
  // A tab left open across a release picks up the new one at its next page change.
  useReloadOnNewRelease();
  return <PlatformProvider><ThemeSync /><AppRoutes /><CapsLockWarning /></PlatformProvider>;
}
