import { useEffect, useState } from "react";
import { Pause, Play } from "lucide-react";
import "./photoCarousel.css";

const reducedMotionQuery = "(prefers-reduced-motion: reduce)";

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => typeof window !== "undefined" && Boolean(window.matchMedia?.(reducedMotionQuery).matches));
  useEffect(() => {
    const query = window.matchMedia?.(reducedMotionQuery);
    if (!query) return undefined;
    const update = () => setReduced(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

// Crossfading photos that advance every `interval` ms (4 seconds by default), with a gentle zoom
// on the photo in view. `startDelay` offsets the first switch, so several carousels side by side
// don't all change at once. It pauses while hovered or focused and from its own button, and stays
// on one still photo when the viewer prefers reduced motion. `children(slide, index)` renders text over the photos.
export function PhotoCarousel({ slides, interval = 4000, startDelay = 0, label, className = "", children }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [held, setHeld] = useState(false);
  const [started, setStarted] = useState(false);
  const reduced = usePrefersReducedMotion();
  const running = slides.length > 1 && !paused && !held && !reduced;
  useEffect(() => {
    if (!running) return undefined;
    // Keyed on the index, so choosing a slide restarts the full interval.
    const timer = window.setTimeout(() => {
      setStarted(true);
      setIndex((current) => (current + 1) % slides.length);
    }, interval + (started ? 0 : startDelay));
    return () => window.clearTimeout(timer);
  }, [running, index, interval, startDelay, started, slides.length]);
  const slide = slides[index];
  return (
    <section className={`photoCarousel ${className}`.trim()} aria-roledescription="carousel" aria-label={label}
      onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setHeld(false); }}>
      <div className="photoCarouselSlides">
        {slides.map((item, position) => (
          <figure key={item.src} className={position === index ? "isActive" : undefined} aria-hidden={position !== index}
            role="group" aria-roledescription="slide" aria-label={`${position + 1} of ${slides.length}`}>
            <img src={item.src} alt={item.alt} width={item.width} height={item.height}
              loading={position === 0 ? "eager" : "lazy"} decoding="async" />
          </figure>
        ))}
      </div>
      {children && <div className="photoCarouselContent" aria-live={running ? "off" : "polite"}>{children(slide, index)}</div>}
      {slides.length > 1 && (
        <div className="photoCarouselControls">
          {slides.map((item, position) => (
            <button key={item.src} type="button" className="photoCarouselDot" aria-current={position === index ? "true" : undefined}
              aria-label={`Show slide ${position + 1}: ${item.title || item.alt}`} onClick={() => { setStarted(true); setIndex(position); }} />
          ))}
          {!reduced && (
            <button type="button" className="photoCarouselPause" aria-label={paused ? "Play slideshow" : "Pause slideshow"} onClick={() => setPaused(!paused)}>
              {paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
