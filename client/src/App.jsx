import { AppRoutes } from "./routes/AppRoutes";
import { usePreventNumberScroll } from "./core/forms/usePreventNumberScroll";
export default function App() {
  usePreventNumberScroll();
  return <AppRoutes />;
}
