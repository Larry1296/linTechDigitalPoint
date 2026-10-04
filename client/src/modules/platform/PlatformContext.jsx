import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../../core/api/client";
const defaultPlatform = { name: import.meta.env.VITE_PLATFORM_NAME || "DukaFlow", contact_email: "" };
const PlatformContext = createContext(defaultPlatform);
export function PlatformProvider({ children }) {
  const [platform, setPlatform] = useState(defaultPlatform);
  useEffect(() => { api("/api/v1/tenancy/platform/").then((data) => setPlatform({ ...defaultPlatform, ...data })).catch(() => {}); }, []);
  // The browser tab carries the platform's name, never a subscriber's.
  useEffect(() => { if (!window.location.pathname.startsWith("/r/")) document.title = platform.name; }, [platform.name]);
  return <PlatformContext.Provider value={platform}>{children}</PlatformContext.Provider>;
}
export function usePlatform() { return useContext(PlatformContext); }
