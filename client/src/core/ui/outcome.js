import Swal from "sweetalert2";

// Every save ends in an overlay: success or error. After a success the form that was submitted is reset
// for the next entry; after an error its fields are kept so only the mistake needs fixing.
//
// A save is a changing request (POST, PATCH, …) made within a minute of submitting a form or confirming a dialog.
// When all of them have finished without an error, the success overlay shows: the page's own success message if it
// shows one (FormSuccess, showSuccess), otherwise a plain "Saved". Errors come from the request, FormError or showError.
//
// Once a staff page's form has saved, the page is done: it closes and returns to the page it was opened from. Screens
// where many entries are made one after another stay open for the next (STAY), as does a form in a dialog (closing
// the dialog is its close) or one marked data-stay; a page that has already moved on by itself is left where it went.

let enabled = true;
let pending = null; // { form: HTMLFormElement | null, at: time, where: the page's address when submitted }
let inflight = 0;
let failed = false;
let timer;
const WINDOW = 60000;
const SETTLE = 700; // time for the page to show its own success message first

export const outcomeOverlays = () => enabled;
export function setOutcomeOverlays(on) { enabled = on; pending = null; inflight = 0; failed = false; clearTimeout(timer); }

// The till, the M-Pesa agency, the stock count, a chama's payments and the cyber job queue take entry after entry.
const STAY = [/^\/admin\/pos\b/, /^\/admin\/mpesa\b/, /^\/admin\/stock-check\b/, /^\/admin\/chama\/\d+/, /^\/admin\/cyber\/jobs\b/];
const address = () => (typeof window === "undefined" ? "" : window.location.pathname + window.location.search);

export function returnToPrevious(form, where) {
  if (!form || form.closest("[data-stay], [role='dialog'], dialog")) return false;
  const path = window.location.pathname;
  if (address() !== where || !path.startsWith("/admin/") || STAY.some((stay) => stay.test(path))) return false;
  if (!(window.history.state?.idx > 0)) return false; // opened directly: there is no page of this app to go back to
  window.history.back();
  return true;
}

const live = () => pending && Date.now() - pending.at < WINDOW;
const heading = (form) => form?.querySelector("h1, h2, h3, legend")?.textContent?.trim() || form?.getAttribute("aria-label") || "";

function start(form) {
  pending = { form, at: Date.now(), where: address() };
  inflight = 0;
  failed = false;
  clearTimeout(timer);
}

if (typeof document !== "undefined") {
  document.addEventListener("submit", (event) => { if (event.target instanceof HTMLFormElement) start(event.target); }, true);
}

// A confirmed dialog (confirmAction, askForm) also starts a save, keeping the form if one was just submitted.
export function beginAction() {
  if (live()) pending.at = Date.now();
  else start(null);
}

// A card in the middle of the screen in the page's own theme, with the page blurred behind it (styles: .outcomeOverlay).
// A success confirms what was just done and closes by itself; an error waits to be read and closed.
function overlay(icon, title, text) {
  const error = icon === "error";
  return Swal.fire({ icon, title, text, buttonsStyling: false, returnFocus: true,
    ...(error ? { confirmButtonText: "Close" } : { showConfirmButton: false, timer: 1600, timerProgressBar: true }),
    customClass: { container: "outcomeOverlay", popup: `outcomeCard ${error ? "outcomeError" : "outcomeSuccess"}`, confirmButton: "outcomeButton" } });
}

async function succeed(title, text) {
  const { form, where } = pending;
  pending = null;
  clearTimeout(timer);
  await overlay("success", title, text);
  if (form?.isConnected) {
    form.reset();
    form.dispatchEvent(new Event("outcome-reset"));
    returnToPrevious(form, where);
  }
}

// Called by api(): true when this request is part of a save.
export function mutationStarted(path) {
  if (!enabled || !live()) return false;
  if (path.startsWith("/api/v1/auth/")) { pending = null; return false; } // signing in or unlocking is not a save
  inflight += 1;
  clearTimeout(timer);
  return true;
}

export function mutationFinished(ok, message) {
  inflight = Math.max(0, inflight - 1);
  if (!ok) {
    failed = true;
    pending = null;
    clearTimeout(timer);
    void overlay("error", "Could not save", message);
    return;
  }
  if (inflight === 0 && !failed) {
    clearTimeout(timer);
    timer = setTimeout(() => { if (live() && inflight === 0) void succeed("Saved", heading(pending.form)); }, SETTLE);
  }
}

// The page's own messages: shown full screen, and a success one stands in for the plain "Saved".
export function showOutcome(kind, title, text) {
  if (!enabled) return Promise.resolve();
  if (kind === "error") {
    pending = null;
    clearTimeout(timer);
    return overlay("error", title, text);
  }
  if (live()) return succeed(title, text);
  return overlay("success", title, text);
}
