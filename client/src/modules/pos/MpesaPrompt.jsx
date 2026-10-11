import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, Smartphone, XCircle } from "lucide-react";
import { api } from "../../core/api/client";
import { businessCurrency } from "../../core/organization/presentation";
import "./mpesaPrompt.css";

const POLL_MS = 3000;

// Whether this business can send M-Pesa prompts (a till or paybill set up in Settings → M-Pesa payments).
export function useMpesaExpress() {
  const [express, setExpress] = useState(null);
  useEffect(() => {
    let live = true;
    api("/api/v1/commerce/mpesa-express/").then((data) => { if (live) setExpress(data && !Array.isArray(data) ? data : null); }).catch(() => {});
    return () => { live = false; };
  }, []);
  return express;
}

// A prompt sent to a customer's phone, followed until they pay, cancel or it fails. ``onDone`` runs once with the result.
export function usePrompt(initial, onDone) {
  const [prompt, setPrompt] = useState(initial);
  const done = useRef(onDone);
  useEffect(() => { done.current = onDone; });
  useEffect(() => setPrompt(initial), [initial]);
  useEffect(() => {
    if (!prompt || prompt.status !== "PENDING") return undefined;
    const timer = setTimeout(async () => {
      try {
        const next = await api(`/api/v1/commerce/prompts/${prompt.id}/`);
        setPrompt(next);
        if (next.status !== "PENDING") done.current?.(next);
      } catch { setPrompt({ ...prompt }); /* try again on the next tick */ }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [prompt]);
  return prompt;
}

export const shownPhone = (phone) => String(phone || "").replace(/^254/, "0");

// The prompt's state, as a customer at the counter would want it said.
export function PromptStatus({ prompt }) {
  if (!prompt) return null;
  const amount = `${businessCurrency()} ${Number(prompt.amount).toLocaleString()}`;
  if (prompt.status === "PENDING") return <p className="mpesaPrompt pending" role="status">
    <Loader2 size={18} className="spin" aria-hidden="true" />
    <span><b>Prompt sent to {shownPhone(prompt.phone)}</b> for {amount}. Waiting for the customer to enter their M-Pesa PIN…</span>
  </p>;
  if (prompt.status === "COMPLETED") return <p className="mpesaPrompt paid" role="status">
    <CheckCircle2 size={18} aria-hidden="true" />
    <span><b>Paid {amount}</b> · M-Pesa code {prompt.receipt_number}{prompt.detail?.includes("could not be confirmed") ? `. ${prompt.detail}` : ""}</span>
  </p>;
  return <p className="mpesaPrompt failed" role="status">
    <XCircle size={18} aria-hidden="true" />
    <span><b>Not paid.</b> {prompt.detail}</span>
  </p>;
}

// Send (or send again) the prompt for a sale's waiting M-Pesa payment.
export function SendPrompt({ paymentId, defaultPhone = "", label = "Send M-Pesa prompt", onSent }) {
  const [phone, setPhone] = useState(defaultPhone);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const send = async (event) => {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      onSent(await api(`/api/v1/commerce/payments/${paymentId}/prompt/`, { method: "POST", body: JSON.stringify({ phone }) }));
    } catch (err) {
      setError(err.message);
    } finally { setBusy(false); }
  };
  return <form className="sendPrompt" onSubmit={send}>
    <label>Customer's M-Pesa number
      <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" required placeholder="0712 345 678" maxLength={16} />
    </label>
    <button disabled={busy || !phone.trim()}><Smartphone size={16} aria-hidden="true" /> {busy ? "Sending…" : label}</button>
    {error && <p className="formNotice error" role="alert">{error}</p>}
  </form>;
}

// For an M-Pesa payment still waiting (Sales): send the customer the prompt, and follow it until it is paid.
export function PromptForWaiting({ paymentId, defaultPhone = "", onPaid }) {
  const [sent, setSent] = useState(null);
  const prompt = usePrompt(sent, (done) => { if (done.status === "COMPLETED") onPaid?.(); });
  return <div className="promptForWaiting">
    {prompt?.status !== "PENDING" && <SendPrompt paymentId={paymentId} defaultPhone={shownPhone(prompt?.phone) || defaultPhone}
      label={prompt ? "Send the prompt again" : "Send M-Pesa prompt"} onSent={setSent} />}
    <PromptStatus prompt={prompt} />
  </div>;
}
