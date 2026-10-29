// The length of a password this tab last opened something with (never the password itself), so a password field can
// try what is typed by itself the moment it is as long as the real one. "sign-in" is the sign-in password (the lock
// screen). Kept for this tab only and forgotten on sign-out.
const KEY = "workspace-password-length";
const key = (kind) => `${KEY}:${kind}`;

export function rememberPasswordLength(password, kind = "sign-in") {
  try { if (password) sessionStorage.setItem(key(kind), String(password.length)); } catch { /* Storage may be disabled. */ }
}
export function knownPasswordLength(kind = "sign-in") {
  try { return Number(sessionStorage.getItem(key(kind))) || null; } catch { return null; }
}
export function forgetPasswordLength() {
  try { for (const kind of ["sign-in"]) sessionStorage.removeItem(key(kind)); } catch { /* Storage may be disabled. */ }
}
