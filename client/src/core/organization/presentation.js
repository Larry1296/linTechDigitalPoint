// Presentation only. Backend authorization always uses validated session membership.
let organization = null;
export function setBusinessPresentation(value) { organization = value || null; }
export function businessCurrency() { const code = organization?.currency || "KES"; return code === "KES" ? "KSh" : code; }
export function businessTimeZone() { return organization?.timezone || "Africa/Nairobi"; }
