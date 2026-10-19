// Presentation only. Backend authorization always uses validated session membership.
let organization = null;
export function setBusinessPresentation(value) { organization = value || null; }
export function businessCurrency() { const code = organization?.currency || "KES"; return code === "KES" ? "KSh" : code; }
export function businessTimeZone() { return organization?.timezone || "Africa/Nairobi"; }
// Today's date and the time now where the business is, for form defaults. toISOString() gives the UTC date, which
// in Nairobi is still yesterday until 3 a.m., so a sale made then would fall outside "up to today".
export function businessToday(now = new Date()) { return new Intl.DateTimeFormat("en-CA", { timeZone: businessTimeZone() }).format(now); }
export function businessNow(now = new Date()) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: businessTimeZone(), year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(now).replace(" ", "T");
}
