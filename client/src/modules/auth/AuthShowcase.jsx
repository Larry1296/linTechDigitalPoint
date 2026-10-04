import { useEffect, useState } from "react";
import { PhotoCarousel } from "../../components/PhotoCarousel";
import "./authShowcase.css";

const WIDE = "(min-width: 761px)";

function useWideScreen() {
  const [wide, setWide] = useState(() => typeof window !== "undefined" && Boolean(window.matchMedia?.(WIDE).matches));
  useEffect(() => {
    const query = window.matchMedia?.(WIDE);
    if (!query) return undefined;
    const update = () => setWide(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return wide;
}

// The side panel of the split sign-in and sign-up pages. On wide screens it advertises the
// platform with a photo slideshow, one feature per slide; on phones, where the panel sits above
// the form, it shows the page's own short introduction (`children`) and loads no photos.
// Each page passes its own `slides` (see AUTH_SLIDES in showcase.js).
export function AuthShowcase({ slides, children }) {
  if (!useWideScreen()) return children;
  return (
    <PhotoCarousel slides={slides} label="What you can do with the platform" className="authShowcase">
      {(slide) => (
        <div className="authShowcaseText" key={slide.src}>
          <span className="eyebrow">{slide.title}</span>
          <h2>{slide.heading}</h2>
          <p>{slide.text}</p>
        </div>
      )}
    </PhotoCarousel>
  );
}
