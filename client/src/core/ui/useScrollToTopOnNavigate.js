import { useEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

// A page opened from a link or the menu starts at its top, so it shows centred or from its beginning instead of at the
// scroll position the last page was left at. Back and forward keep the browser's own position (and pages that
// remember theirs, such as the shop's listings); a link to a section (#contact) is left to the page that has it.
// The jump is instant: gliding up a long page someone has just left would only look slow.
export function useScrollToTopOnNavigate() {
  const { pathname, hash } = useLocation();
  const type = useNavigationType();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (type === "POP" || hash) return;
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [pathname]); // only a new page, not a new #section or ?page
}
