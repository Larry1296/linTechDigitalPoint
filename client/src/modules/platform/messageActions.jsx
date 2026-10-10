import { useEffect, useState } from "react";
import { Check, Copy, Pencil, Share2 } from "lucide-react";

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

// Hands text to the phone's share sheet (WhatsApp, SMS, email…). Where the browser has none (a computer, or a page
// over plain http), it opens WhatsApp with the text ready to send.
export async function shareText(text) {
  if (navigator.share) {
    try { await navigator.share({ text }); return; } catch (error) { if (error.name === "AbortError") return; }
  }
  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
}

// The buttons under a chat message. ``what`` names it for screen readers ("question" or "answer"); ``onEdit`` adds Edit.
export function MessageActions({ text, what, onEdit }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  const button = (label, icon, onClick) => (
    <button type="button" className="helpChatAction" onClick={onClick} aria-label={label} title={label}>{icon}</button>
  );
  return (
    <div className="helpChatActions" role="group" aria-label={`${what} actions`}>
      {button(copied ? "Copied" : `Copy ${what}`, copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />,
        async () => setCopied(await copyText(text.trim())))}
      {onEdit && button(`Edit ${what}`, <Pencil size={15} aria-hidden="true" />, onEdit)}
      {button(`Share ${what}`, <Share2 size={15} aria-hidden="true" />, () => void shareText(text.trim()))}
    </div>
  );
}
