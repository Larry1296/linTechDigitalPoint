import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";

// Puts text on the clipboard. The Clipboard API needs a secure page (https or localhost); on the shop's local network
// over plain http it is missing, so the old way is used there: select a hidden copy of the text and copy that.
export async function copyText(text) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* fall back below */ }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
  document.body.appendChild(area);
  area.select();
  try { return document.execCommand("copy"); } catch { return false; } finally { area.remove(); }
}

// One tap copies a whole chat message, so nothing has to be highlighted by hand.
export function CopyButton({ text, label = "Copy" }) {
  const [state, setState] = useState("idle");
  useEffect(() => {
    if (state === "idle") return undefined;
    const timer = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(timer);
  }, [state]);
  const copy = async () => setState((await copyText(text.trim())) ? "copied" : "failed");
  return (
    <button type="button" className="helpChatCopy" onClick={() => void copy()} aria-label={state === "copied" ? "Copied" : label} title={label}>
      {state === "copied" ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      <span>{state === "copied" ? "Copied" : state === "failed" ? "Could not copy" : "Copy"}</span>
    </button>
  );
}
