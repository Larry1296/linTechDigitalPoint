import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../../core/api/client";
import { PUBLIC_PATHS } from "../../seo/publicPages";
const defaultPlatform = { name: import.meta.env.VITE_PLATFORM_NAME || "DukaFlow", contact_email: "" };
const PlatformContext = createContext(defaultPlatform);
export function PlatformProvider({ children }) {
  const [platform, setPlatform] = useState(defaultPlatform);
  useEffect(() => { api("/api/v1/tenancy/platform/").then((data) => setPlatform({ ...defaultPlatform, ...data })).catch(() => {}); }, []);
  // The browser tab carries the platform's name, never a subscriber's. A public page keeps the title its HTML
  // gave it (src/seo/publicPages.js), which is what search engines that run the page read.
  useEffect(() => {
    const path = window.location.pathname.replace(/(.)\/+$/, "$1");
    if (!path.startsWith("/r/") && !PUBLIC_PATHS.includes(path)) document.title = platform.name;
  }, [platform.name]);
  return <PlatformContext.Provider value={platform}>{children}</PlatformContext.Provider>;
}
export function usePlatform() { return useContext(PlatformContext); }
