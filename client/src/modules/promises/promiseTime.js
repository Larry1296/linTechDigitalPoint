import { businessTimeZone } from "../../core/organization/presentation";

// "Tue 24 Nov, 10:00 am", where the business is.
export const when = (iso) => new Intl.DateTimeFormat("en-GB", { timeZone: businessTimeZone(), weekday: "short", day: "numeric", month: "short",
  hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(iso));

// How far off a time is, in words: "3 hours", "2 days", "25 minutes".
function span(ms) {
  const minutes = Math.max(1, Math.round(Math.abs(ms) / 60000));
  if (minutes < 60) return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} ${hours === 1 ? "hour" : "hours"}`;
  const days = Math.round(hours / 24);
  return `${days} days`;
}

// "Late by 2 hours" or "Due in 3 hours".
export const dueIn = (iso, now = Date.now()) => {
  const ms = new Date(iso).getTime() - now;
  return ms <= 0 ? `Late by ${span(ms)}` : `Due in ${span(ms)}`;
};

// The value a datetime-local field shows for a moment, in this device's time.
export const forField = (date) => {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

// Quick picks for when to answer the customer. Whole days land at 10 am, and never on a Sunday, when the business is
// closed: that moves to the Monday.
export function quickPick(kind, now = new Date()) {
  if (kind === "hours") return new Date(now.getTime() + 2 * 3600000);
  const days = { tomorrow: 1, three: 3, week: 7 }[kind];
  const at = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, 10, 0);
  if (at.getDay() === 0) at.setDate(at.getDate() + 1);
  return at;
}

export const QUICK_PICKS = [["hours", "In 2 hours"], ["tomorrow", "Tomorrow"], ["three", "In 3 days"], ["week", "In a week"]];

// A phone number as a link the phone can call: spaces and dashes dropped.
export const telLink = (phone) => `tel:${String(phone).replace(/[^\d+]/g, "")}`;
