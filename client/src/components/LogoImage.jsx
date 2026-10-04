import { useEffect, useState } from "react";

// Each place a logo appears gives it the same visual weight: the logo is sized by area, so a wide
// wordmark gets more width (keeping its letters readable) and a square mark gets more height.
// Header and footer slots also grow with the screen, so logos stay prominent on large monitors.
export const LOGO_SLOTS = {
  // Uploads are cropped to the design itself, so these sizes are the logo's own size, not its canvas.
  // The header grows at most 1.15x on large monitors so the logo stays inside the 88px content height.
  header: { area: 12000, minHeight: 44, maxHeight: 76, maxWidth: 280, responsive: true, maxScale: 1.15 },
  footer: { area: 14000, minHeight: 48, maxHeight: 84, maxWidth: 320, responsive: true },
  receipt: { area: 21000, minHeight: 56, maxHeight: 112, maxWidth: 340 },
  preview: { area: 26000, minHeight: 64, maxHeight: 128, maxWidth: 420 },
};
const DESIGN_WIDTH = 1366;

// 1 at a typical laptop; up to 1.6 on large monitors; down to 0.85 on small screens.
export function screenScale(viewportWidth) {
  return Math.min(1.6, Math.max(0.85, viewportWidth / DESIGN_WIDTH));
}

export function logoWidth(aspect, slot, screen = 1) {
  const { area, minHeight, maxHeight, maxWidth, maxScale = Infinity } = LOGO_SLOTS[slot];
  const scale = Math.min(screen, maxScale);
  const height = Math.min(maxHeight * scale, Math.max(minHeight * scale, Math.sqrt((area * scale * scale) / aspect)));
  return Math.round(Math.min(maxWidth * scale, height * aspect));
}

function useScreenScale(enabled) {
  const [scale, setScale] = useState(() => (enabled && typeof window !== "undefined" ? screenScale(window.innerWidth) : 1));
  useEffect(() => {
    if (!enabled) return undefined;
    const update = () => setScale(screenScale(window.innerWidth));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [enabled]);
  return scale;
}

export function LogoImage({ src, alt, slot, className = "" }) {
  const [aspect, setAspect] = useState(null);
  const scale = useScreenScale(Boolean(LOGO_SLOTS[slot].responsive));
  const width = aspect ? logoWidth(aspect, slot, scale) : undefined;
  return <img className={`logoImage logoImage-${slot} ${className}`.trim()} src={src} alt={alt}
    style={width ? { width } : undefined} data-sized={aspect ? "true" : undefined}
    onLoad={(event) => {
      const { naturalWidth, naturalHeight } = event.currentTarget;
      if (naturalWidth && naturalHeight) setAspect(naturalWidth / naturalHeight);
    }} />;
}
