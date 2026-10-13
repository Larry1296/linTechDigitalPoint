import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

export const DASHBOARD = "/admin/dashboard";
export const STOCK_SEARCH_ID = "stock-quick-search";

// Typing in a box, or a pop-up is open: keys belong to it (Home moves the cursor, "/" is typed).
function busy(event) {
  const target = event.target;
  if (!(target instanceof Element)) return false;
  if (target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']")) return true;
  return Boolean(target.closest("dialog, [role='dialog'], [role='alertdialog'], .swal2-container") || document.querySelector(".swal2-container"));
}

/** Keys that work anywhere in the business workspace, so it can be run from the keyboard:
 * Home goes back to the dashboard; "/" jumps into the "Do we have it?" stock search. */
export function useKeyboardShortcuts() {
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (event) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || busy(event)) return;
      if (event.key === "Home" && !event.shiftKey) {
        event.preventDefault();
        if (window.location.pathname !== DASHBOARD) navigate(DASHBOARD);
        else window.scrollTo({ top: 0 });
      } else if (event.key === "/") {
        const search = document.getElementById(STOCK_SEARCH_ID);
        event.preventDefault();
        if (search) search.focus();
        else navigate(DASHBOARD, { state: { focusStockSearch: true } });
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate]);
}
