import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "../core/ui/theme";

export function ThemePicker() {
  const [theme, setTheme] = useTheme();
  const Icon = theme === "system" ? Monitor : theme === "dark" ? Moon : Sun;
  return (
    <label className="theme" title="Choose your appearance">
      <Icon size={18} aria-hidden="true" />
      <span className="sr">Theme</span>
      <select aria-label="Theme" value={theme} onChange={(event) => setTheme(event.target.value)}>
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}
