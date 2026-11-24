// Fingerprint, face or eye unlock (WebAuthn). The phone or computer keeps a key it opens only after its own fingerprint,
// face or eye check, and signs the server's request with it. This browser remembers which people turned it on here,
// so the lock screen offers it only where it works.

import { Fingerprint, ScanFace } from "lucide-react";

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
// Each person who turned it on in this browser: their key here, and the username shown on the sign-in page.
const entry = (value) => (typeof value === "string" ? { credentialId: value, username: "" } : value || null);
// The key this browser made for the person, if any.
export const keyHere = (userId) => (userId == null ? null : entry(stored()[userId])?.credentialId || null);
export function rememberKey(userId, credentialId, username = "") { save({ ...stored(), [userId]: { credentialId, username } }); }
export function forgetKey(userId) { const all = stored(); delete all[userId]; save(all); }
// The people who can sign in here with their fingerprint or face, the most recent first.
export const signInsHere = () => Object.entries(stored()).map(([userId, value]) => ({ userId, ...entry(value) }))
  .filter((item) => item.credentialId).reverse();
export function forgetCredential(credentialId) {
  save(Object.fromEntries(Object.entries(stored()).filter(([, value]) => entry(value)?.credentialId !== credentialId)));
}

// What this device's own check is called, to name it on the buttons. Browsers say only that a device has a check
// (biometricAvailable), not which kind, so the kind comes from the device: iPhones with the notch or island use Face ID
// and the others Touch ID; Macs Touch ID; Windows Windows Hello. Android phones may use a fingerprint, the face or the
// eyes, whichever the owner set up, so they are named by what most have.
export function deviceCheck() {
  const ua = navigator.userAgent || "";
  const longSide = Math.max(window.screen?.width || 0, window.screen?.height || 0);
  const iPad = /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  if (/iPhone/.test(ua)) return longSide >= 812 ? { name: "Face ID", Icon: ScanFace } : { name: "Touch ID", Icon: Fingerprint };
  if (iPad) return { name: "Face ID or Touch ID", Icon: ScanFace };
  if (/Macintosh/.test(ua)) return { name: "Touch ID", Icon: Fingerprint };
  if (/Windows/.test(ua)) return { name: "Windows Hello", Icon: ScanFace };
  return { name: "fingerprint or face", Icon: Fingerprint };
}

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
    excludeCredentials: descriptors(options.excludeCredentials), hints: ["client-device"] } });
  return { id: credential.id, rawId: toText(credential.rawId), type: credential.type, response: {
    clientDataJSON: toText(credential.response.clientDataJSON), attestationObject: toText(credential.response.attestationObject),
    transports: credential.response.getTransports?.() || [] } };
}

export async function signWithKey(options) {
  // "client-device": the key is on this phone or computer, so the browser goes straight to its fingerprint or face
  // check rather than first asking where the key is (with a Continue to press).
  const credential = await navigator.credentials.get({ publicKey: {
    ...options, challenge: toBytes(options.challenge), allowCredentials: descriptors(options.allowCredentials), hints: ["client-device"] } });
  return { id: credential.id, rawId: toText(credential.rawId), type: credential.type, response: {
    clientDataJSON: toText(credential.response.clientDataJSON), authenticatorData: toText(credential.response.authenticatorData),
    signature: toText(credential.response.signature),
    userHandle: credential.response.userHandle ? toText(credential.response.userHandle) : null } };
}

// The person closed the fingerprint or face prompt, or it timed out: nothing to report.
export const cancelled = (error) => error?.name === "NotAllowedError" || error?.name === "AbortError";

// Signs in with the key this browser made: the server's request, the device's fingerprint or face check, the answer.
// Returns what the password sign-in returns. A key the server no longer knows is forgotten here.
export async function signInWithKey(api, credentialId) {
  try {
    const { options } = await api("/api/v1/auth/biometric/sign-in/start/", { method: "POST", body: JSON.stringify({ credential_id: credentialId }) });
    const credential = await signWithKey(options);
    return await api("/api/v1/auth/biometric/sign-in/", { method: "POST", body: JSON.stringify({ credential }) });
  } catch (error) {
    if (error?.data?.code === "biometric_unknown") forgetCredential(credentialId);
    throw error;
  }
}
