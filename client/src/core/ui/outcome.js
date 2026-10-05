import Swal from "sweetalert2";

// Every save ends in a full-screen overlay: success or error. After a success the form that was submitted is reset
// for the next entry; after an error its fields are kept so only the mistake needs fixing.
//
// A save is a changing request (POST, PATCH, …) made within a minute of submitting a form or confirming a dialog.
// When all of them have finished without an error, the success overlay shows: the page's own success message if it
// shows one (FormSuccess, showSuccess), otherwise a plain "Saved". Errors come from the request, FormError or showError.

let enabled = true;
let pending = null; // { form: HTMLFormElement | null, at: time }
let inflight = 0;
let failed = false;
let timer;
const WINDOW = 60000;
const SETTLE = 700; // time for the page to show its own success message first

export const outcomeOverlays = () => enabled;
export function setOutcomeOverlays(on) { enabled = on; pending = null; inflight = 0; failed = false; clearTimeout(timer); }

const live = () => pending && Date.now() - pending.at < WINDOW;
const heading = (form) => form?.querySelector("h1, h2, h3, legend")?.textContent?.trim() || form?.getAttribute("aria-label") || "";

function start(form) {
  pending = { form, at: Date.now() };
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

function overlay(icon, title, text) {
  return Swal.fire({ icon, title, text, grow: "fullscreen", confirmButtonText: icon === "error" ? "Close" : "Done",
    customClass: { container: "outcomeOverlay" } });
}

async function succeed(title, text) {
  const { form } = pending;
  pending = null;
  clearTimeout(timer);
  await overlay("success", title, text);
  if (form?.isConnected) {
    form.reset();
    form.dispatchEvent(new Event("outcome-reset"));
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
