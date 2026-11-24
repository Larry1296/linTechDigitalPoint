// Fingerprint, face or eye unlock (WebAuthn). The phone or computer keeps a key it opens only after its own fingerprint,
// face or eye check, and signs the server's request with it. This browser remembers which people turned it on here,
// so the lock screen offers it only where it works.

const STORE = "lintech-biometric";

const toBytes = (text) => {
  const base64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
};
const toText = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

export async function biometricAvailable() {
  try {
    return Boolean(window.PublicKeyCredential && await window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable());
  } catch { return false; }
}

function stored() {
  try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; }
}
function save(all) {
  try { localStorage.setItem(STORE, JSON.stringify(all)); } catch { /* Storage may be disabled. */ }
}
// The key this browser made for the person, if any.
export const keyHere = (userId) => (userId == null ? null : stored()[userId] || null);
export function rememberKey(userId, credentialId) { save({ ...stored(), [userId]: credentialId }); }
export function forgetKey(userId) { const all = stored(); delete all[userId]; save(all); }

// A short name for the device, shown in Settings beside each device that has it on.
export function deviceLabel() {
  const ua = navigator.userAgent || "";
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "iPad";
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? "Android phone" : "Android tablet";
  if (/Windows/.test(ua)) return "Windows computer";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/CrOS/.test(ua)) return "Chromebook";
  return "This device";
}

const descriptors = (list) => (list || []).map((item) => ({ ...item, id: toBytes(item.id) }));

export async function makeKey(options) {
  const credential = await navigator.credentials.create({ publicKey: {
    ...options, challenge: toBytes(options.challenge), user: { ...options.user, id: toBytes(options.user.id) },
    excludeCredentials: descriptors(options.excludeCredentials) } });
  return { id: credential.id, rawId: toText(credential.rawId), type: credential.type, response: {
    clientDataJSON: toText(credential.response.clientDataJSON), attestationObject: toText(credential.response.attestationObject),
    transports: credential.response.getTransports?.() || [] } };
}

export async function signWithKey(options) {
  const credential = await navigator.credentials.get({ publicKey: {
    ...options, challenge: toBytes(options.challenge), allowCredentials: descriptors(options.allowCredentials) } });
  return { id: credential.id, rawId: toText(credential.rawId), type: credential.type, response: {
    clientDataJSON: toText(credential.response.clientDataJSON), authenticatorData: toText(credential.response.authenticatorData),
    signature: toText(credential.response.signature),
    userHandle: credential.response.userHandle ? toText(credential.response.userHandle) : null } };
}

// The person closed the fingerprint or face prompt, or it timed out: nothing to report.
export const cancelled = (error) => error?.name === "NotAllowedError" || error?.name === "AbortError";
