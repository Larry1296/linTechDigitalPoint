// The length of the password this tab last signed in or unlocked with (never the password itself), so the lock screen
// can try a typed password by itself the moment it is as long as the real one. Kept for this tab only and forgotten
// on sign-out.
const KEY = "workspace-password-length";

export function rememberPasswordLength(password) {
  try { if (password) sessionStorage.setItem(KEY, String(password.length)); } catch { /* Storage may be disabled. */ }
}
export function knownPasswordLength() {
  try { return Number(sessionStorage.getItem(KEY)) || null; } catch { return null; }
}
export function forgetPasswordLength() {
  try { sessionStorage.removeItem(KEY); } catch { /* Storage may be disabled. */ }
}
