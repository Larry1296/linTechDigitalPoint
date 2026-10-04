import { useEffect, useRef } from "react";
import { businessTimeZone } from "../../core/organization/presentation";

// The calendar date (YYYY-MM-DD) in the business's time zone, so "today" turns over at its midnight.
export const businessDate = (value = new Date()) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: businessTimeZone(), year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));

// Calls onNewDay once the business date changes (just after 00:00). Checked every 30 seconds and whenever
// the tab comes back into view, since a sleeping laptop or phone pauses timers.
export function useNewBusinessDay(onNewDay) {
  const day = useRef(businessDate());
  const callback = useRef(onNewDay);
  useEffect(() => {
    callback.current = onNewDay;
  });
  useEffect(() => {
    const check = () => {
      if (businessDate() !== day.current) {
        day.current = businessDate();
        callback.current();
      }
    };
    const timer = setInterval(check, 30_000);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, []);
}
